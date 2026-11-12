"""Read a bounded text excerpt from a Tavily source, without forwarding credentials."""
import asyncio
from ipaddress import ip_address, ip_network

import dns.asyncresolver
import dns.exception
import httpx
from bs4 import BeautifulSoup

from services import ServiceError

MAX_BYTES = 512 * 1024
MAX_CHARS = 6000
DEADLINE = 12  # seconds for DNS, connection, headers and body combined


async def addresses(host):
    try:
        return [ip_address(host)]
    except ValueError:
        resolver = dns.asyncresolver.Resolver()
        result = await resolver.resolve_name(host, search=False, lifetime=4)
        return [ip_address(value) for value in result.addresses()]


def public(address):
    if not address.is_global or address.is_multicast or address.is_reserved:
        return False
    if address.version == 6:
        # Use native global unicast only; exclude mapped and transition addresses.
        return (address in ip_network('2000::/3') and address.sixtofour is None
                and address.teredo is None and not address.is_site_local)
    return True


async def fetch(url):
    if (len(url) > 4096 or '\\' in url or any(ord(c) < 33 or ord(c) == 127 for c in url)):
        raise ServiceError('Invalid webpage URL.')
    parsed = httpx.URL(url)
    host = parsed.raw_host.decode('ascii')
    if (parsed.scheme not in ('http', 'https') or not host or parsed.userinfo
            or parsed.port not in (None, 80 if parsed.scheme == 'http' else 443)
            or '%' in host or host.rstrip('.').lower().split('.')[-1] in ('localhost', 'local', 'internal')):
        raise ServiceError('Webpage address is not permitted.')
    resolved = await addresses(host)
    if not resolved or not all(public(ip) for ip in resolved):
        raise ServiceError('Webpage does not resolve exclusively to public addresses.')
    # Pin the connection to a checked IP. Keep the real hostname for TLS verification
    # and HTTP routing. No second DNS lookup, ambient proxy, cookies or API headers.
    target = parsed.copy_with(host=str(next((ip for ip in resolved if ip.version == 4), resolved[0])))
    headers = {'Host': parsed.netloc.decode('ascii'), 'Accept-Encoding': 'identity',
               'Accept': 'text/html, text/plain'}
    async with httpx.AsyncClient(trust_env=False, timeout=5, follow_redirects=False) as client:
        async with client.stream('GET', target, headers=headers,
                                 extensions={'sni_hostname': host}) as response:
            if response.is_redirect:
                raise ServiceError('Redirect blocked. Select a direct Tavily source.')
            response.raise_for_status()
            mime = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
            if mime not in ('text/html', 'text/plain'):
                raise ServiceError('Only HTML and plain-text webpages are supported.')
            if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                raise ServiceError('Compressed webpages are not accepted.')
            if int(response.headers.get('Content-Length', 0)) > MAX_BYTES:
                raise ServiceError('Webpage exceeds the download limit.')
            body = bytearray()
            async for chunk in response.aiter_raw():
                if len(body) + len(chunk) > MAX_BYTES:
                    raise ServiceError('Webpage exceeds the download limit.')
                body.extend(chunk)
            encoding = (response.charset_encoding or 'utf-8').lower()
            if encoding not in ('utf-8', 'ascii', 'iso-8859-1', 'windows-1252'):
                encoding = 'utf-8'
            text = body.decode(encoding, errors='replace')
    if mime == 'text/html':
        soup = BeautifulSoup(text, 'html.parser')
        for tag in soup.find_all(['script', 'style', 'template', 'noscript', 'head', 'nav', 'footer']):
            tag.decompose()
        text = (soup.find('main') or soup.body or soup).get_text(' ', strip=True)
    text = ' '.join(text.split())
    if not text:
        raise ServiceError('No readable text found.')
    return {'text': text[:MAX_CHARS], 'truncated': len(text) > MAX_CHARS}


def read_webpage(url, sources):
    source = next((s for s in sources if s['url'] == url), None)
    if source is None or not isinstance(url, str):
        raise ServiceError('Choose an exact URL returned by Tavily in this run.')

    async def bounded():
        async with asyncio.timeout(DEADLINE):
            return await fetch(url)

    try:
        return {'source_id': source['id'], 'url': url, **asyncio.run(bounded())}
    except (TimeoutError, httpx.TimeoutException, dns.exception.Timeout) as exc:
        raise ServiceError('Webpage request timed out.') from exc
    except (dns.exception.DNSException, httpx.HTTPError, httpx.InvalidURL, ValueError, OSError) as exc:
        raise ServiceError('Unable to retrieve this webpage.') from exc
