"""Run with: python -m streamlit run app.py"""
import json
from uuid import uuid4

import streamlit as st

from agent import MAX_ITERATIONS, research_steps
from config import load_settings
from services import ResearchModel, WebSearch

st.set_page_config(page_title='Product Research Agent', page_icon='🔎', layout='wide')
st.title('Multi-Agent Product Review and Comparison System')
st.caption(f'Milestone II · Product Research Agent · Maximum {MAX_ITERATIONS} agent decisions')
st.write('Enter a specific product and model. The agent chooses its searches and cites retrieved web evidence.')

with st.form('research_form'):
    product = st.text_input('Product name', max_chars=200, placeholder='e.g. Sony WH-1000XM5')
    submitted = st.form_submit_button('Research Product')

def advance(steps, decision=None):
    with st.spinner('Researching product and recording the execution trace...'):
        try:
            url = next(steps) if decision is None else steps.send(decision)
        except StopIteration as done:
            st.session_state.report = done.value
            return
        st.session_state.pending_read = (uuid4().hex, steps, url)


if submitted:
    previous = st.session_state.pop('pending_read', None)
    if previous:
        previous[1].close()
    st.session_state.pop('report', None)
    if not product.strip():
        st.warning('Please enter a product name.')
    else:
        try:
            try:
                secrets = dict(st.secrets)
            except FileNotFoundError:
                secrets = {}
            settings = load_settings(secrets)
            advance(research_steps(product, ResearchModel(settings['GROQ_API_KEY'], settings['GROQ_MODEL']),
                                   WebSearch(settings['TAVILY_API_KEY'])))
        except ValueError as exc:
            st.error(str(exc))

def resolve_pending(token, approved):
    pending = st.session_state.get('pending_read')
    if pending and pending[0] == token:
        st.session_state.pop('pending_read')
        advance(pending[1], approved)


if 'pending_read' in st.session_state:
    token, _, url = st.session_state.pending_read
    st.subheader('Approve webpage read')
    st.write('The agent proposes read_webpage with these arguments. Approve once to fetch this URL, or skip to continue without fetching it.')
    st.code(json.dumps({'url': url}, ensure_ascii=False), language='json')
    st.button('Approve this read', key='approve_' + token, on_click=resolve_pending, args=(token, True))
    st.button('Skip this read', key='skip_' + token, on_click=resolve_pending, args=(token, False))

if 'report' in st.session_state:
    report = st.session_state.report
    st.subheader(f"Research: {report['product']}")
    st.info(f"Stopping reason: {report['stopping_reason']} · Decisions: {report['iterations']}/{report['max_iterations']}")
    sources = {s['id']: s for s in report['sources']}
    for key, title in [('description', 'Product description'), ('details', 'Relevant product details'),
                       ('findings', 'Supported findings')]:
        st.subheader(title)
        if not report['answer'][key]:
            st.write('No supported statements available.')
        for claim in report['answer'][key]:
            st.write(claim['text'])
            for sid in claim['source_ids']:
                st.link_button(f"Source {sid}: {sources[sid]['title']}", sources[sid]['url'])
    for limitation in report['answer']['limitations']:
        st.warning(limitation)
    st.caption('Claims use search excerpts and any retrieved page text. Citation IDs are checked; factual support still needs review.')
    with st.expander('Retrieved sources and evidence'):
        for source in report['sources']:
            st.link_button(f"[{source['id']}] {source['title']}", source['url'])
            st.text(source['content'])
            for event in report['trace']:
                page = event.get('observation', {})
                if event.get('tool') == 'read_webpage' and page.get('source_id') == source['id']:
                    st.caption('Read from webpage' + (' (excerpt)' if page['truncated'] else ''))
                    st.text(page['text'])
    with st.expander('Execution trace (observable actions only)'):
        st.json(report['trace'])
    st.download_button('Download execution trace (JSON)',
                       data=json.dumps(report, indent=2, ensure_ascii=False),
                       file_name='product_research_trace.json', mime='application/json')
