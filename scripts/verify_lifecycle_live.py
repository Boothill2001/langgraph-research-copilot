"""Live safety check: metered DeepSeek, real MCP, retrieval and graph checkpoints."""
import asyncio
import json
from pathlib import Path
import sys
import time
import requests
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from copilot.engine import Engine
from copilot.security import USERS,issue
from copilot.store import Store
RAG='http://127.0.0.1:8011'
def post(path,payload):
    r=requests.post(RAG+path,json=payload,headers={'Authorization':'Bearer '+issue(USERS['curator'])},timeout=180)
    r.raise_for_status()
    return r.json()
async def main():
    registry=requests.get(RAG+'/research/lifecycle',headers={'Authorization':'Bearer '+issue(USERS['curator'])}).json()
    published=[r for r in registry['revisions'] if r['source']=='lifecycle-demo' and r['status']=='published']
    if published:
        revision=published[-1]['revision']
    else:
        staged=post('/research/curator/refresh',{'source_id':'lifecycle-demo','text':f'# SYNTHETIC live harness\nThe current demo review budget is 137 units. Verification run {time.time_ns()}.'})
        revision=staged['revision']
        post('/research/curator/publish',{'source_id':'lifecycle-demo','revision':revision})
    store=Store(); engine=Engine(store)
    request='Search ONLY source lifecycle-demo: What is the current demo review budget? Save a short cited report.'
    paused=store.create(USERS['researcher'],request)
    for _ in range(8):
        run=await engine.advance(paused)
        if run['status']=='error':
            raise RuntimeError(run['state']['error'])
        if run['state'].get('evidence'):
            break
    assert run['state'].get('evidence') and run['state']['next_node']=='planner',run['state']
    assert {e['source_id'] for e in run['state']['evidence']}=={'lifecycle-demo'}
    pending=store.create(USERS['researcher'],request)
    draft_run=await engine.run_until_pause(pending)
    assert draft_run['status']=='awaiting_approval',draft_run
    old_hash=draft_run['state']['draft']['hash']
    store.approve(pending,USERS['reviewer'],old_hash,True)
    with store.db() as c:
        before=c.execute('SELECT count(*) FROM api_calls WHERE run_id=?',(paused,)).fetchone()[0]
    post('/research/curator/withdraw',{'source_id':'lifecycle-demo','revision':revision})
    after_search=await engine.run_until_pause(paused)
    after_draft=await engine.run_until_pause(pending,{'approved':True})
    with store.db() as c:
        after=c.execute('SELECT count(*) FROM api_calls WHERE run_id=?',(paused,)).fetchone()[0]
        reports=c.execute('SELECT count(*) FROM reports WHERE run_id IN (?,?)',(paused,pending)).fetchone()[0]
        approvals=c.execute('SELECT count(*) FROM approvals WHERE run_id=?',(pending,)).fetchone()[0]
    assert before==after and reports==0 and approvals==0
    for result in [after_search,after_draft]:
        assert result['status']=='completed' and result['state']['evidence']==[] and result['state']['observations']==[]
        assert not store.get_draft(result['id'])
    output={'kind':'Live local integration; not a quality benchmark','created':time.time(),'source':'lifecycle-demo','revision':revision,
        'paused_after_search':{'run_id':paused,'llm_calls_before_withdraw':before,'llm_calls_after_resume':after,'status':after_search['status'],'context_scrubbed':True},
        'approved_pending_draft':{'run_id':pending,'old_hash':old_hash,'status':after_draft['status'],'approvals_remaining':approvals},
        'new_reports':reports,'runtime':'Actual LangGraph SQLite checkpoints + MCP stdio + DeepSeek + RAG service'}
    (ROOT/'artifacts/lifecycle-live.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps(output,indent=2))
if __name__=='__main__':
    asyncio.run(main())
