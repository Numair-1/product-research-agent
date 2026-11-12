"""Offline tests use explicit test doubles, never a production demo-data mode."""
import os
import unittest
from unittest.mock import Mock, patch

import requests
import httpx
from groq import RateLimitError
from streamlit.testing.v1 import AppTest

from agent import research_product
from config import load_settings
from services import ResearchModel, ServiceError, WebSearch


def answer(source_id=1):
    return {'description': [{'text': 'Fixture product description.', 'source_ids': [source_id]}],
            'details': [], 'findings': [], 'limitations': ['Test fixture only.']}


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.model = Mock()
        self.search = Mock()
        self.search.search.return_value = [
            {'title': 'Test fixture', 'url': 'https://example.com/test', 'content': 'Fixture evidence.'}]

    def test_search_then_finish_trace_and_sources(self):
        self.model.decide.side_effect = [('web_search', {'query': 'fixture specs'}),
                                         ('finish_research', answer())]
        report = research_product('Fixture', self.model, self.search)
        self.assertEqual(report['stopping_reason'], 'completed')
        self.assertEqual(report['iterations'], 2)
        self.assertEqual(report['sources'][0]['url'], 'https://example.com/test')
        self.assertEqual([e['event'] for e in report['trace']],
                         ['decision_summary', 'tool_call', 'tool_observation'] * 2
                         + ['final_answer', 'stop'])

    def test_hard_limit(self):
        self.model.decide.return_value = ('web_search', {'query': 'fixture'})
        report = research_product('Fixture', self.model, self.search)
        self.assertEqual(report['stopping_reason'], 'iteration_limit')
        self.assertEqual(self.model.decide.call_count, 4)
        self.assertEqual(self.search.search.call_count, 4)
        self.assertEqual(len(report['sources']), 1)

    def test_failed_search_can_recover(self):
        self.search.search.side_effect = [ServiceError('Search failed'), self.search.search.return_value]
        self.model.decide.side_effect = [('web_search', {'query': 'first'}),
                                         ('web_search', {'query': 'retry'}), ('finish_research', answer())]
        self.assertEqual(research_product('Fixture', self.model, self.search)['stopping_reason'], 'completed')

    def test_empty_results(self):
        self.search.search.return_value = []
        empty = {'description': [], 'details': [], 'findings': [], 'limitations': ['No evidence found.']}
        self.model.decide.side_effect = [('web_search', {'query': 'fixture'}), ('finish_research', empty)]
        report = research_product('Fixture', self.model, self.search)
        self.assertEqual(report['stopping_reason'], 'insufficient_evidence')
        self.assertEqual(report['trace'][2]['observation']['status'], 'empty_results')

    def test_invented_citations_rejected(self):
        self.model.decide.return_value = ('finish_research', answer(999))
        report = research_product('Fixture', self.model, self.search)
        self.assertEqual(report['stopping_reason'], 'iteration_limit')
        self.assertEqual(report['answer']['description'], [])

    def test_model_failure(self):
        self.model.decide.side_effect = ServiceError('Model unavailable')
        report = research_product('Fixture', self.model, self.search)
        self.assertEqual(report['stopping_reason'], 'model_error')
        self.assertEqual(report['trace'][-1]['event'], 'stop')

    def test_blank_input(self):
        self.assertEqual(research_product(' ', self.model, self.search)['stopping_reason'], 'invalid_input')
        self.model.decide.assert_not_called()

    @patch('config.load_dotenv')
    def test_credentials_missing_or_from_secrets(self, _):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'Missing API keys'):
                load_settings()
            settings = load_settings({'GROQ_API_KEY': 'test', 'TAVILY_API_KEY': 'test'})
            self.assertEqual(settings['GROQ_API_KEY'], 'test')

    @patch('services.requests.post')
    def test_real_search_adapter_contract(self, post):
        post.return_value.json.return_value = {'results': self.search.search.return_value}
        self.assertEqual(len(WebSearch('test').search('fixture')), 1)
        self.assertEqual(post.call_args.kwargs['json']['query'], 'fixture')
        post.return_value.json.return_value = {'results': []}
        self.assertEqual(WebSearch('test').search('fixture'), [])
        post.return_value.json.return_value = {'unexpected': []}
        with self.assertRaises(ServiceError):
            WebSearch('test').search('fixture')
        post.side_effect = requests.Timeout('sensitive raw error')
        with self.assertRaisesRegex(ServiceError, '^Web search failed'):
            WebSearch('test').search('fixture')

    @patch('services.Groq')
    def test_model_adapter_contract(self, client):
        call = Mock(type='function')
        call.function.arguments = '{"query":"fixture"}'
        call.function.name = 'web_search'
        client.return_value.chat.completions.create.return_value.choices = [Mock(message=Mock(tool_calls=[call]))]
        model = ResearchModel('test', 'openai/gpt-oss-20b')
        self.assertEqual(model.decide('Fixture', [], 1), ('web_search', {'query': 'fixture'}))
        request = client.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(request['model'], 'openai/gpt-oss-20b')
        self.assertEqual(request['tools'][0]['function']['name'], 'web_search')
        self.assertFalse(request['parallel_tool_calls'])
        client.assert_called_once_with(api_key='test', timeout=45, max_retries=0)

    @patch('services.Groq')
    def test_groq_rate_limit_is_safe_and_not_retried(self, client):
        create = client.return_value.chat.completions.create
        create.side_effect = RateLimitError(
            'sensitive provider response',
            response=httpx.Response(429, request=httpx.Request('POST', 'https://api.groq.com')),
            body=None,
        )
        with self.assertRaisesRegex(ServiceError, 'Wait and retry later'):
            ResearchModel('test', 'openai/gpt-oss-20b').decide('Fixture', [], 1)
        self.assertEqual(create.call_count, 1)

    @patch('services.Groq')
    def test_invalid_groq_response(self, client):
        create = client.return_value.chat.completions.create
        create.return_value.choices = []
        model = ResearchModel('test', 'openai/gpt-oss-20b')
        with self.assertRaises(ServiceError):
            model.decide('Fixture', [], 1)
        call = Mock(type='function')
        create.return_value.choices = [Mock(message=Mock(tool_calls=[call]))]
        for invalid in ('not json', '[]'):
            call.function.arguments = invalid
            with self.assertRaisesRegex(ServiceError, 'invalid tool arguments'):
                model.decide('Fixture', [], 1)


class InterfaceTests(unittest.TestCase):
    def test_initial_and_blank_input(self):
        app = AppTest.from_file('app.py').run()
        self.assertFalse(app.exception)
        app.button[0].click().run()
        self.assertIn('enter a product', app.warning[0].value)

    @patch('config.load_dotenv')
    def test_missing_keys(self, _):
        with patch.dict(os.environ, {'GROQ_API_KEY': '', 'TAVILY_API_KEY': ''}):
            app = AppTest.from_file('app.py')
            app.secrets = {}
            app.run()
            app.text_input[0].set_value('Fixture')
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertIn('Missing API keys', app.error[0].value)

    @patch('services.WebSearch.search')
    @patch('services.ResearchModel.decide')
    @patch('config.load_settings')
    def test_report_and_download(self, settings, decide, search):
        settings.return_value = {'GROQ_API_KEY': 'test', 'TAVILY_API_KEY': 'test', 'GROQ_MODEL': 'openai/gpt-oss-20b'}
        decide.side_effect = [('web_search', {'query': 'fixture'}), ('finish_research', answer())]
        search.return_value = [{'title': 'Fixture', 'url': 'https://example.com/test', 'content': 'Test only.'}]
        app = AppTest.from_file('app.py').run()
        app.text_input[0].set_value('Fixture')
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['report']['stopping_reason'], 'completed')
        self.assertEqual(len(app.get('download_button')), 1)
        app.run()  # Report and download survive reruns.
        self.assertEqual(len(app.get('download_button')), 1)


if __name__ == '__main__':
    unittest.main()
