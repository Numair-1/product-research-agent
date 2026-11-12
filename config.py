"""Read local credentials without including them in reports or traces."""
import os
from pathlib import Path

from dotenv import load_dotenv


def load_settings(secrets=None):
    load_dotenv(Path(__file__).parent / '.env', override=False)
    secrets = secrets or {}
    settings = {}
    for name in ('GROQ_API_KEY', 'TAVILY_API_KEY', 'GROQ_MODEL'):
        settings[name] = str(os.getenv(name) or secrets.get(name, '')).strip()
    settings['GROQ_MODEL'] = settings['GROQ_MODEL'] or 'openai/gpt-oss-20b'
    missing = [name for name in ('GROQ_API_KEY', 'TAVILY_API_KEY')
               if not settings[name]]
    if missing:
        raise ValueError('Missing API keys: ' + ', '.join(missing)
                         + '. Set them in .env, environment variables, or Streamlit secrets.')
    return settings
