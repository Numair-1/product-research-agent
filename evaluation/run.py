"""Offline reporting; live, sequential trials using the unmodified application."""
import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
from agent import MAX_ITERATIONS, research_product, validate_answer
from config import load_settings
from services import ResearchModel, WebSearch, ServiceError
from dotenv import load_dotenv

CASES = json.loads((HERE / 'cases.json').read_text(encoding='utf-8'))
SECTIONS = ('description', 'details', 'findings')


class Paused(Exception):
    """Do not score a trial interrupted by provider limits or account access."""


class PacedModel(ResearchModel):
    last_request = 0.0
    requests = 0
    throttles = 0

    def decide(self, *args):
        for attempt in range(2):
            time.sleep(max(0, self.last_request + 2.2 - time.monotonic()))
            self.last_request = time.monotonic()
            self.requests += 1
            try:
                return super().decide(*args)
            except ServiceError as exc:
                cause = exc.__cause__
                status = getattr(cause, 'status_code', None)
                if status in (401, 403):
                    raise Paused('Groq access denied') from None
                if status != 429:
                    raise
                self.throttles += 1
                try:
                    seconds = float(cause.response.headers.get('retry-after', '60'))
                except (ValueError, TypeError):
                    seconds = 60
                if attempt or not math.isfinite(seconds) or seconds > 90:
                    raise Paused('Groq rate limit; retry later') from None
                # Replay only this decision, never the earlier search or page read.
                time.sleep(max(3, seconds + 1))


class MeteredSearch(WebSearch):
    calls = 0

    def search(self, query):
        self.calls += 1
        try:
            return super().search(query)
        except ServiceError as exc:
            status = getattr(getattr(exc.__cause__, 'response', None), 'status_code', None)
            if status in (401, 402, 403, 429, 432, 433):
                raise Paused(f'Tavily access/quota (HTTP {status})') from None
            raise


def grade(case, r):
    trace = r['trace']
    reasons = []
    if not (0 <= r['iterations'] <= MAX_ITERATIONS and trace[-1]['event'] == 'stop'
            and trace[-1]['reason'] == r['stopping_reason']
            and trace[-2]['event'] == 'final_answer'):
        reasons.append('invalid trace or decision bound')
    calls = [e['tool'] for e in trace if e['event'] == 'tool_call']
    observations = [e for e in trace if e['event'] == 'tool_observation']
    claims = [c for s in SECTIONS for c in r['answer'][s]]
    if case['kind'] == 'input_edge':
        if (r['stopping_reason'] != 'invalid_input' or r['iterations'] or calls
                or r['sources'] or claims):
            reasons.append('invalid input was not rejected before research')
    else:
        if r['stopping_reason'] != 'completed':
            reasons.append('stop=' + r['stopping_reason'])
        if not any(e['tool'] == 'web_search' and e['observation'].get('results') for e in observations):
            reasons.append('no search evidence')
        try:
            validate_answer(r['answer'], r['sources'])
        except ValueError:
            reasons.append('invalid citations/report')
        evidence = {s['id']: s['content'] for s in r['sources']}
        for e in observations:
            o = e['observation']
            if e['tool'] == 'read_webpage' and o.get('status') == 'ok' and o['source_id'] in evidence:
                evidence[o['source_id']] += ' ' + o['text']
        matches = re.compile(case['pattern'], re.I | re.S).search
        hits = [c for c in claims if matches(c['text'])]
        if not hits:
            reasons.append('expected fact absent from claims')
        elif not any(matches(evidence.get(i, '')) for c in hits for i in c['source_ids']):
            reasons.append('expected fact absent from linked evidence')
    return reasons


def report(out, rows, k):
    scored = {(r['case'], r['round']): r for r in rows if r['status'] in ('pass','fail')}
    def metric(cases, rounds):
        eligible = [c for c in cases if all((c['id'], n) in scored for n in rounds)]
        passed = sum(all(scored[c['id'], n]['status'] == 'pass' for n in rounds) for c in eligible)
        return f'{passed}/{len(eligible)} ({100*passed/len(eligible):.1f}%)' if eligible else 'N/A (0 eligible)'
    lines = ['# Milestone II live evaluation', '',
             f'Requested: {len(CASES)} cases × {k} independent agent invocations. '
             f'Completed and scored: {len(scored)}/{len(CASES)*k}.',
             '', 'pass@1 = fraction of cases whose first scheduled run passed. '
             f'pass^{k} = fraction for which **all {k} runs passed**, not “at least one”. '
             'Each column uses only cases with its required runs complete. N/A is not zero.', '',
             f'| Cohort | pass@1 | pass^{k} |', '|---|---:|---:|']
    for group, subset in [('All', CASES), ('Product research', [c for c in CASES if c['kind']=='research']),
                          ('Input validation (no network)', [c for c in CASES if c['kind']=='input_edge'])]:
        lines.append(f'| {group} | {metric(subset,[1])} | {metric(subset,range(1,k+1))} |')
    lines += ['', '| Case | Runs in order | Observed failures / missing coverage |','|---|---|---|']
    for c in CASES:
        cells, notes = [], []
        for n in range(1,k+1):
            entries = [r for r in rows if (r['case'],r['round'])==(c['id'],n)]
            row = entries[-1] if entries else {}
            cells.append(row.get('status','not run'))
            if row.get('reasons'):
                notes.append(f"run {n}: " + ', '.join(row['reasons']))
        lines.append(f"| {c['id']} | {' / '.join(cells)} | {'; '.join(notes) or '—'} |")
    stopped = [r for r in rows if r['status']=='blocked']
    lines += ['', '## Execution and interpretation', '',
              'Groq requests (including retries): '+str(sum(r['groq_requests'] for r in rows))+
              '; Groq 429 responses: '+str(sum(r['throttles'] for r in rows))+
              '; Tavily searches: '+str(sum(r['searches'] for r in rows))+'.',
              'Reader observations: '+str(dict(sum((Counter(r.get('reads',{})) for r in rows), Counter())))+'.',
              'The two input-edge cases execute the real validation path and should use zero provider calls. '
              'All other trials use the production Groq, Tavily, and webpage implementations without mocks. '
              'Page reading is optional, so a failed read does not by itself fail a cited answer.',
              'Gold facts and manufacturer references are in cases.json. The deterministic grader checks '
              'the expected fact in a claim and in a source cited by that claim. It does not establish '
              'semantic entailment or detect every contradiction or unsupported secondary claim. '
              'Three trials per case are descriptive, not a population reliability estimate.']
    if stopped:
        lines.append('Provider interruptions (unscored): '+ '; '.join(r['case']+': '+r['reasons'][0] for r in stopped)+
                     '. Not-run cells after an interruption were not submitted.')
    if rows:
        lines.append(f"Model: {rows[0]['model']}; timestamps (UTC): {rows[0]['utc']} through {rows[-1]['utc']}.")
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--k',type=int,default=3)
    p.add_argument('--out',type=Path,default=HERE/'post-gate-results')
    p.add_argument('--interactive', action='store_true', help='Ask for human approval for each URL; default skips all reads.')
    p.add_argument('--env-file',type=Path,help='Optional private local .env; never copied to results')
    p.add_argument('--report-only',action='store_true')
    args=p.parse_args()
    if args.k < 3: p.error('k must be at least 3')
    out=args.out; out.mkdir(parents=True,exist_ok=True)
    if out.resolve() == (HERE/'results').resolve():
        p.error('Archived pre-gate results are read-only. Open results/REPORT.md or choose a new --out.')
    path=out/'runs.jsonl'
    rows=[json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []
    files=[HERE/'cases.json',Path(__file__)]+[APP/f for f in ('agent.py','services.py','webpage.py','config.py')]
    signature=hashlib.sha256(b'\0'.join(f.read_bytes().replace(b'\r\n',b'\n') for f in files)).hexdigest()
    if any(r['signature']!=signature or r['k']!=args.k for r in rows):
        p.error('Different code, dataset, or k. Use a fresh --out directory.')
    if args.report_only:
        report(out,rows,args.k);return
    if args.env_file: load_dotenv(args.env_file,override=False)
    settings=load_settings()
    policy='interactive' if args.interactive else 'deny'
    if any(r.get('approval_policy')!=policy for r in rows):
        p.error('Approval policy changed; choose a fresh --out directory.')
    def approve(url):
        print('read_webpage arguments:',json.dumps({'url':url},ensure_ascii=True))
        try:
            return input('Approve this one read? Type APPROVE: ') == 'APPROVE'
        except EOFError:
            return False
    if any(r['model']!=settings['GROQ_MODEL'] for r in rows):p.error('Model changed; use fresh --out.')
    model=PacedModel(settings['GROQ_API_KEY'],settings['GROQ_MODEL'])
    search=MeteredSearch(settings['TAVILY_API_KEY'])
    done={(r['case'],r['round']) for r in rows if r['status']!='blocked'}
    # Complete zero-cost controls first. Product trials run sequentially in rounds.
    for kind in ('input_edge','research'):
        for n in range(1,args.k+1):
            for c in CASES:
                if c['kind']!=kind or (c['id'],n) in done:continue
                before=(model.requests,model.throttles,search.calls)
                row=dict(case=c['id'],round=n,k=args.k,model=settings['GROQ_MODEL'],signature=signature,approval_policy=policy)
                try:
                    result=research_product(c['input'],model,search,approve_read=approve if args.interactive else None)
                    reasons=grade(c,result)
                    row.update(status='fail' if reasons else 'pass',reasons=reasons,
                               iterations=result['iterations'],stop=result['stopping_reason'],
                               source_count=len(result['sources']),reads=dict(Counter(
                                   e['observation']['status'] for e in result['trace']
                                   if e['event']=='tool_observation' and e['tool']=='read_webpage')))
                except Paused as exc:
                    row.update(status='blocked',reasons=[str(exc)])
                row.update(utc=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                           groq_requests=model.requests-before[0],throttles=model.throttles-before[1],
                           searches=search.calls-before[2])
                with path.open('a',encoding='utf-8') as f:
                    f.write(json.dumps(row)+'\n'); f.flush(); os.fsync(f.fileno())
                rows.append(row);report(out,rows,args.k)
                print(f"{c['id']} run {n}: {row['status']} "+'; '.join(row['reasons']),flush=True)
                if row['status']=='blocked':return


if __name__=='__main__':
    main()
