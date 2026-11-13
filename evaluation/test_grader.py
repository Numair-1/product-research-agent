"""Offline checks for metric arithmetic and grading only; never evaluation trials."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from run import CASES, grade, report


class GraderChecks(TestCase):
    def test_fact_must_be_supported_by_its_own_citation(self):
        case = next(c for c in CASES if c['id']=='pico')
        answer = {'description':[{'text':'RP2040', 'source_ids':[1]}],
                  'details':[], 'findings':[], 'limitations':[]}
        sources = [{'id':1,'content':'Other fact'}, {'id':2,'content':'RP2040'}]
        r = dict(iterations=2, stopping_reason='completed', answer=answer, sources=sources,
                 trace=[dict(event='tool_observation', tool='web_search', observation={'results':sources}),
                        dict(event='final_answer'), dict(event='stop',reason='completed')])
        self.assertIn('expected fact absent from linked evidence', grade(case,r))
        answer['description'][0]['source_ids']=[2]
        self.assertEqual(grade(case,r),[])

    def test_first_vs_every_trial_and_blocked_denominator(self):
        rows = [dict(case=c, round=n, status=status, reasons=[], groq_requests=0,
                     throttles=0, searches=0, utc='test', model='test')
                for c,seq in [('pico',['pass','fail','pass']),('uno',['pass','pass','pass']),
                              ('mega',['pass'])] for n,status in enumerate(seq,1)]
        rows.append(dict(rows[-1],round=2,status='blocked',reasons=['quota']))
        with TemporaryDirectory() as tmp:
            report(Path(tmp),rows,3)
            self.assertIn('| All | 3/3 (100.0%) | 1/2 (50.0%) |',
                          (Path(tmp)/'REPORT.md').read_text(encoding='utf-8'))
