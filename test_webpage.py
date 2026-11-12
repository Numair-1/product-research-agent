"""Exercise the reader and agent without contacting live hosts or using keys."""
import asyncio
from ipaddress import ip_address
import unittest
from unittest.mock import patch, Mock

import httpx

from agent import research_product
from services import ServiceError
import webpage

URL = 'https://vendor.example/specs'
ROW = {'url': URL, 'title': 'Specs', 'content': 'Search excerpt'}
SOURCES = [{'id': 1, **ROW}]
PUBLIC = ip_address('93.184.216.34')


class Body(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


class ReaderTests(unittest.TestCase):
    def setUp(self):
        # Only DNS and the HTTP transport are simulated. The real request building,
        # allowlist, IP checks, streaming, extraction and agent validation all run.
        self.dns = self.enterContext(patch('webpage.addresses', return_value=[PUBLIC]))
        self.headers = {'Content-Type': 'text/html'}
        self.status = 200
        self.body = [b'<head><title>Ignore</title></head><main><script>hidden</script>',
                     b'<p>Product weighs <b>200 g</b>.</p></main>']
        self.requests = []
        def respond(request):
            self.requests.append(request)
            return httpx.Response(self.status, headers=self.headers, stream=Body(self.body))
        real_client = httpx.AsyncClient
        self.enterContext(patch('webpage.httpx.AsyncClient', side_effect=lambda **opts:
                                real_client(transport=httpx.MockTransport(respond), **opts)))

    def read(self):
        return webpage.read_webpage(URL, SOURCES)

    def test_pinned_request_and_visible_text(self):
        result = self.read()
        self.assertEqual(result['source_id'], 1)
        self.assertIn('200 g', result['text'])
        self.assertNotIn('hidden', result['text'])
        req, = self.requests
        self.assertEqual(req.url.host, str(PUBLIC))
        self.assertEqual(req.headers['Host'], 'vendor.example')
        self.assertEqual(req.extensions['sni_hostname'], 'vendor.example')
        self.assertNotIn('Authorization', req.headers)
        self.assertNotIn('Cookie', req.headers)
        self.dns.assert_awaited_once_with('vendor.example')

    def test_no_unsourced_url(self):
        with self.assertRaisesRegex(ServiceError, 'returned by Tavily'):
            webpage.read_webpage(URL + '/other', SOURCES)
        self.dns.assert_not_awaited()
        self.assertFalse(self.requests)

    def test_disallowed_urls(self):
        for url in ('file:///example', 'http://localhost/', 'http://x.localhost/',
                    'https://vendor.example:8443/', 'https://user:pass@vendor.example/'):
            with self.subTest(url=url), self.assertRaises(ServiceError):
                webpage.read_webpage(url, [{'id': 1, 'url': url}])
        self.dns.assert_not_awaited()
        self.assertFalse(self.requests)

    def test_nonpublic_or_mixed_dns_fails_before_connect(self):
        for value in ('127.0.0.1', '10.2.0.1', '169.254.1.2', '100.64.0.1',
                      '::1', 'fc00::1', 'ff02::1', '::ffff:127.0.0.1', '224.0.0.1'):
            self.dns.return_value = [PUBLIC, ip_address(value)]
            with self.subTest(value=value), self.assertRaisesRegex(ServiceError, 'public'):
                self.read()
        self.assertFalse(self.requests)

    def test_redirect_is_never_followed(self):
        self.status = 302
        self.headers['Location'] = 'http://127.0.0.1/'
        with self.assertRaisesRegex(ServiceError, 'Redirect blocked'):
            self.read()
        self.assertEqual(len(self.requests), 1)

    def test_size_limit_with_and_without_content_length(self):
        with patch('webpage.MAX_BYTES', 4):
            self.headers['Content-Length'] = '8'
            with self.assertRaisesRegex(ServiceError, 'download limit'):
                self.read()
            del self.headers['Content-Length']
            self.body = [b'123', b'45']
            with self.assertRaisesRegex(ServiceError, 'download limit'):
                self.read()

    def test_reject_compressed_binary_and_empty(self):
        for headers, body, message in [
            ({'Content-Type': 'text/html', 'Content-Encoding': 'gzip'}, b'x', 'Compressed'),
            ({'Content-Type': 'application/pdf'}, b'x', 'Only HTML'),
            ({'Content-Type': 'text/html'}, b'<script>hidden</script>', 'No readable')]:
            self.headers, self.body = headers, [body]
            with self.subTest(headers=headers), self.assertRaisesRegex(ServiceError, message):
                self.read()

    def test_timeout_includes_lookup(self):
        async def slow(host):
            await asyncio.sleep(1)
        self.dns.side_effect = slow
        with patch('webpage.DEADLINE', 0.02), self.assertRaisesRegex(ServiceError, 'timed out'):
            self.read()
        self.assertFalse(self.requests)

    def test_plain_text_excerpt_limit(self):
        self.headers = {'Content-Type': 'text/plain'}
        self.body = [b'abcdef']
        with patch('webpage.MAX_CHARS', 3):
            result = self.read()
        self.assertEqual(result['text'], 'abc')
        self.assertTrue(result['truncated'])

    def test_agent_recovers_then_reads_and_cites_original_source(self):
        search = Mock()
        search.search.return_value = [ROW]
        model = Mock()
        answer = {'description': [], 'details': [{'text': 'Weight: 200 g', 'source_ids': [1]}],
                  'findings': [], 'limitations': []}
        model.decide.side_effect = [('web_search', {'query': 'weight'}),
                                    ('read_webpage', {'url': URL + '/other'}),
                                    ('read_webpage', {'url': URL}), ('finish_research', answer)]
        report = research_product('Fixture', model, search)
        self.assertEqual(report['stopping_reason'], 'completed')
        self.assertEqual(report['iterations'], 4)
        observations = [e['observation'] for e in report['trace'] if e['event'] == 'tool_observation']
        self.assertEqual(observations[1]['status'], 'read_failed')
        self.assertIn('200 g', observations[2]['text'])
        self.assertEqual(report['answer']['details'][0]['source_ids'], [observations[2]['source_id']])
        self.assertEqual(len(report['sources']), 1)
