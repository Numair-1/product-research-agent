"""One bounded agent: decide -> act -> observe -> repeat or stop."""
from datetime import datetime, timezone

from services import MAX_ITERATIONS, ServiceError
from webpage import read_webpage

SECTIONS = ('description', 'details', 'findings')


def validate_answer(answer, sources):
    """Reject invented citation IDs; semantic support still needs human review."""
    if not isinstance(answer, dict):
        raise ValueError('Final answer must be an object.')
    allowed = {s['id'] for s in sources}
    for section in SECTIONS:
        if not isinstance(answer.get(section), list):
            raise ValueError('Missing final-answer section.')
        for claim in answer[section]:
            if not isinstance(claim, dict) or not isinstance(claim.get('text'), str) or not claim['text'].strip():
                raise ValueError('Invalid claim text.')
            ids = claim.get('source_ids')
            if not isinstance(ids, list) or not ids or any(type(i) is not int or i not in allowed for i in ids):
                raise ValueError('A claim cited a source not returned by web search.')
    if not isinstance(answer.get('limitations'), list) or any(not isinstance(x, str) for x in answer['limitations']):
        raise ValueError('Invalid limitations.')
    if not any(answer[s] for s in SECTIONS) and not answer['limitations']:
        raise ValueError('An empty report must explain the evidence gap.')
    return {key: answer[key] for key in (*SECTIONS, 'limitations')}


def research_steps(product, model, search):
    """Yield one exact read URL before execution; only literal True authorizes it."""
    product = product.strip()
    trace, history, sources = [], [], []
    started = datetime.now(timezone.utc).isoformat()

    def log(event, iteration, **data):
        trace.append({'event': event, 'iteration': iteration, **data})

    def finish(answer, reason, iteration):
        log('final_answer', iteration, answer=answer, sources=list(sources))
        log('stop', iteration, reason=reason)
        return {'product': product, 'started_at_utc': started,
                'iterations': iteration, 'max_iterations': MAX_ITERATIONS,
                'answer': answer, 'sources': sources, 'stopping_reason': reason,
                'trace': trace}

    def incomplete(message):
        return {**{s: [] for s in SECTIONS}, 'limitations': [message]}

    if not product or len(product) > 200:
        return finish(incomplete('Enter a product name between 1 and 200 characters.'), 'invalid_input', 0)

    for iteration in range(1, MAX_ITERATIONS + 1):
        try:
            action, args = model.decide(product, history, iteration)
        except ServiceError as exc:
            log('decision_summary', iteration, summary='Model decision unavailable.', error=str(exc))
            return finish(incomplete(str(exc)), 'model_error', iteration)

        # These are observable action summaries, not generated private reasoning.
        log('decision_summary', iteration, summary={
            'web_search': 'Agent chose to gather web evidence.',
            'read_webpage': 'Agent chose to read a previously retrieved source.',
            'finish_research': 'Agent chose to submit its research.',
        }.get(action, 'Agent returned an unsupported action.'))
        if action != 'read_webpage':
            log('tool_call', iteration, tool=action, arguments=args)

        if action == 'finish_research':
            try:
                answer = validate_answer(args, sources)
            except ValueError as exc:
                observation = {'error': str(exc)}
            else:
                log('tool_observation', iteration, tool=action, observation={'accepted': True})
                reason = 'completed' if any(answer[s] for s in SECTIONS) else 'insufficient_evidence'
                return finish(answer, reason, iteration)
        elif action == 'read_webpage':
            url = args.get('url') if isinstance(args, dict) else None
            if (not isinstance(url, str) or set(args) != {'url'}
                    or not any(s['url'] == url for s in sources)):
                observation = {'status': 'read_failed', 'error': 'Choose an exact Tavily result URL.'}
            else:
                log('approval_requested', iteration, tool=action, arguments={'url': url})
                approved = (yield url) is True
                log('approval_decision', iteration, tool=action, arguments={'url': url}, approved=approved)
                if not approved:
                    observation = {'status': 'read_skipped', 'error': 'Page read was not approved.'}
                else:
                    log('tool_call', iteration, tool=action, arguments={'url': url})
                    try:
                        page = read_webpage(url, sources)
                        observation = {'status': 'ok', **page}
                    except ServiceError as exc:
                        observation = {'status': 'read_failed', 'error': str(exc)}
        elif action == 'web_search':
            query = args.get('query') if isinstance(args, dict) else None
            if not isinstance(query, str) or not query.strip() or len(query) > 500:
                observation = {'error': 'Search query must contain 1 to 500 characters.'}
            else:
                try:
                    rows = search.search(query.strip())
                    observed = []
                    for row in rows:
                        existing = next((s for s in sources if s['url'] == row['url']), None)
                        if existing is None:
                            existing = {'id': len(sources) + 1, **row}
                            sources.append(existing)
                        observed.append(existing)
                    observation = {'results': observed, 'status': 'ok' if observed else 'empty_results'}
                except ServiceError as exc:
                    observation = {'error': str(exc), 'status': 'search_failed'}
        else:
            observation = {'error': 'Unsupported action. Choose web_search, read_webpage or finish_research.'}

        log('tool_observation', iteration, tool=action, observation=observation)
        history.append({'action': action, 'arguments': args, 'observation': observation})

    return finish(incomplete(f'The {MAX_ITERATIONS}-iteration limit was reached before an acceptable '
                             'final report. Retrieved excerpts remain available below.'),
                  'iteration_limit', MAX_ITERATIONS)


def research_product(product, model, search, approve_read=None):
    """Non-UI callers skip reads unless their human approval callback confirms."""
    steps = research_steps(product, model, search)
    try:
        url = next(steps)
        while True:
            url = steps.send(approve_read(url) if approve_read else False)
    except StopIteration as done:
        return done.value
