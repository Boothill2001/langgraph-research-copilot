"""Document lifecycle workbench, using the existing paper/teal design tokens."""
from datetime import date
import requests
import streamlit as st


def render(base, token, user):
    st.subheader('Document Lifecycle & Applicability')
    st.caption('Real technical documentation + a clearly fictional Policy Lab. Eligibility is enforced before dense search and BM25.')
    if not user:
        st.info('Sign in to inspect sources and run the lab. Use curator to manage sources.')
        return
    def call(path, payload=None):
        response = requests.request('POST' if payload is not None else 'GET', base + path,
            headers={'Authorization': 'Bearer ' + token}, json=payload, timeout=(5,180))
        if not response.ok:
            raise ValueError(str(response.json().get('detail',response.status_code)))
        return response.json()
    try:
        registry = call('/research/lifecycle')
    except Exception as exc:
        st.error(str(exc))
        return
    top = st.columns([2,1,1])
    top[0].markdown('**Eligibility first**  \nACL → publication → applicability  \nThen: dense + BM25 → RRF → rerank → gate')
    top[1].metric('Active generation', registry['generation'][:10] or 'Not initialized')
    top[2].metric('Registry epoch', registry['epoch'])
    explore, manage = st.tabs(['Test applicability', 'Source revisions & curator'])
    with explore:
        left, right = st.columns([1,1.3], gap='large')
        with left:
            st.markdown('#### 1 / The business context')
            corpus = st.selectbox('Corpus', ['policy','technical'], key='lc-corpus')
            if corpus == 'policy':
                st.warning('SYNTHETIC POLICY LAB — fictional rules, not legal or company policy.')
                st.markdown('**Same question. Different purchase date. Different eligible policy.**')
                scenario = st.selectbox('Scenario', ['Old purchase · asked after policy change','New purchase · boundary day','Missing purchase date','Conflicting explicit revision'])
                purchase = None if scenario == 'Missing purchase date' else st.date_input('Purchase date (selects policy)', value=date(2026,11,1) if scenario == 'New purchase · boundary day' else date(2026,10,25)).isoformat()
                st.caption('Question date: 2026-11-21. It does not select the policy version.')
                revision = 'refund_v2' if scenario == 'Conflicting explicit revision' else None
                query = st.text_input('Question', 'How many days do I have to request a refund?')
                source = 'refund'
            else:
                purchase = None
                query = st.text_input('Question', 'How does reciprocal rank fusion combine rankings?')
                source = st.text_input('Source ID (optional)', 'rrf') or None
                revision = st.text_input('Explicit historical revision (optional)', '') or None
            mode = st.selectbox('Retrieval mode', ['hybrid','rerank','dense'], key='lc-mode')
            st.caption('The historical gate was calibrated on the frozen technical corpus. New generations and Policy Lab have no new quality benchmark yet.')
            if st.button('Inspect eligible evidence →', type='primary', key='lc-search'):
                try:
                    with st.spinner('Filtering eligibility, then ranking only permitted chunks…'):
                        st.session_state['lc-result'] = call('/search', {'query':query,'corpus':corpus,'revision':revision,'purchase_date':purchase,'source_id':source,'mode':mode})
                except Exception as exc:
                    st.error(str(exc))
        with right:
            st.markdown('#### 2 / What reached retrieval?')
            result = st.session_state.get('lc-result')
            if not result:
                st.info('Run a scenario. The output will show which version survived eligibility, then the evidence text and provenance.')
            else:
                status = result['status']
                (st.success if status == 'ok' else st.warning)('Result: ' + status)
                trace = result.get('trace',{})
                st.caption('Selection basis: ' + trace.get('selection_basis','—'))
                if trace.get('eligibility'):
                    st.dataframe(trace['eligibility'], hide_index=True, width='stretch')
                for e in result.get('evidence',[]):
                    with st.container(border=True):
                        st.markdown('**' + e['source_id'] + ' · ' + e['revision'] + '**')
                        st.write(e['text'])
                        st.caption('Stable chunk: ' + e['chunk_uid'][:20] + ' · Generation: ' + e['generation'][:10])
                if status == 'needs_context':
                    st.info('Please provide the purchase date. No policy evidence was retrieved.')
                with st.expander('Actual retrieval trace / JSON'):
                    st.json(result)
                if result.get('evidence') and st.button('Revalidate this evidence now',key='lc-validate'):
                    checked = call('/research/validate', {'evidence':result['evidence'],'context':trace['context']})
                    (st.success if checked['valid'] else st.error)('Still eligible' if checked['valid'] else 'Stale evidence — retrieve again')
    with manage:
        rows = registry['revisions']
        st.dataframe([{k:r.get(k) for k in ['source','revision','corpus','workspace','status','start','end']} for r in rows], hide_index=True, width='stretch', height=310)
        if user['role'] == 'curator':
            st.caption('Curator can manage sources owned by the research workspace. Report reviewer approval grants no publication permission.')
            with st.form('lc-stage'):
                st.markdown('#### Refresh a source')
                sid = st.text_input('Source ID', 'lifecycle-demo')
                content = st.text_area('Source content (leave empty to refresh the registered upstream URL)', '# SYNTHETIC lifecycle demo\nThe current demo review budget is 137 units.', height=110)
                if st.form_submit_button('Refresh / stage revision'):
                    try:
                        with st.spinner('Checking cleaned content hash…'):
                            staged = call('/research/curator/refresh', {'source_id':sid,'text':content or None})
                        st.session_state['lc-notice'] = 'Staged ' + staged['revision'] if staged['changed'] else 'Unchanged content — no duplicate revision.'
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
            if st.session_state.get('lc-notice'):
                st.success(st.session_state['lc-notice'])
            own = [r for r in rows if r.get('owner_workspace') == user['workspace']]
            if own:
                selection = st.selectbox('Revision to manage', range(len(own)),format_func=lambda i: own[i]['source']+' · '+own[i]['revision']+' · '+own[i]['status'])
                chosen = own[selection]
                a,b = st.columns(2)
                if a.button('Build & publish generation',disabled=chosen['status']=='withdrawn'):
                    try:
                        with st.spinner('Building and validating an immutable generation. Current index stays live…'):
                            published = call('/research/curator/publish', {'source_id':chosen['source'],'revision':chosen['revision']})
                        st.session_state['lc-notice'] = 'Published ' + published['generation'][:10] + ' — no service restart.'
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
                if b.button('Withdraw revision',disabled=chosen['status']=='withdrawn'):
                    try:
                        call('/research/curator/withdraw',{'source_id':chosen['source'],'revision':chosen['revision']})
                        st.session_state['lc-notice'] = 'Withdrawn immediately. Cached vectors cannot restore eligibility.'
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
        else:
            st.info('Read-only source view. Sign in as curator to refresh, publish or withdraw.')
        with st.expander('Source audit and build history'):
            st.json({'audit':registry['audit'],'builds':registry['builds']})
