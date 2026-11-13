import json
import unittest
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest
from agent import research_product

URL = 'https://example.com/specs?model=A&region=US'
SOURCE = {'url': URL, 'title': 'Specs', 'content': 'Fixture.'}
ANSWER = {'description': [{'text': 'Fixture.', 'source_ids': [1]}], 'findings': [],
          'details': [], 'limitations': []}
ACTIONS = [('web_search', {'query':'fixture'}), ('read_webpage', {'url':URL}),
           ('read_webpage', {'url':URL}), ('finish_research', ANSWER)]


class ApprovalTests(unittest.TestCase):
    def test_noninteractive_default_denies(self):
        model, search = Mock(), Mock()
        model.decide.side_effect = ACTIONS
        search.search.return_value = [SOURCE]
        with patch('agent.read_webpage') as fetch:
            r = research_product('Fixture',model,search)
        fetch.assert_not_called()
        self.assertEqual([e['approved'] for e in r['trace'] if e['event']=='approval_decision'],
                         [False,False])

    def test_ui_exact_arguments_rerun_approve_once_then_skip(self):
        with patch('config.load_settings', return_value={'GROQ_MODEL':'fixture','GROQ_API_KEY':'test',
                                                         'TAVILY_API_KEY':'test'}), \
             patch('services.WebSearch.search',return_value=[SOURCE]) as search, \
             patch('services.ResearchModel.decide',side_effect=ACTIONS) as decide, \
             patch('agent.read_webpage', return_value={'source_id':1,'url':URL,'text':'Fixture.',
                                                       'truncated':False}) as fetch:
            app = AppTest.from_file('app.py').run()
            app.text_input[0].set_value('Fixture')
            app.button[0].click().run()
            self.assertEqual(json.loads(app.code[0].value), {'url':URL})
            app.run()
            fetch.assert_not_called()
            first = app.session_state['pending_read'][0]
            app.button(key='approve_'+first).click().run()
            self.assertFalse(app.exception)
            fetch.assert_called_once_with(URL,[{'id':1,**SOURCE}])
            second = app.session_state['pending_read'][0]
            self.assertNotEqual(first, second)
            app.button(key='skip_'+second).click().run()
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(fetch.call_count,1)
            self.assertEqual(search.call_count,1)
            self.assertEqual(decide.call_count,4)
            r = app.session_state['report']
            self.assertEqual(r['stopping_reason'],'completed')
            self.assertEqual([e['approved'] for e in r['trace'] if e['event']=='approval_decision'],
                             [True,False])
