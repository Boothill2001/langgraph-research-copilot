"""A paused graph cannot reuse withdrawn evidence, even when two models agreed on it."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
import asyncio
import json
from types import SimpleNamespace
from copilot.engine import Engine
from copilot.security import USERS
from copilot.store import Store

E = {'chunk_id':1,'chunk_uid':'uid-1','generation':'a'*32,'revision':'r1','text':'WITHDRAWN_SECRET_TEXT',
     'url':'https://example.com','retrieval_context':{'corpus':'technical'}}


class Provider:
    def __init__(self):
        self.messages = []
        self.after = None
    def call(self, rid, messages, tools=None):
        self.messages.append(messages)
        if tools is None:
            return SimpleNamespace(content=json.dumps({'query':'research', 'source_id':None, 'needs_search':True,
                'wants_report':True,'needs_calculation':False}))
        ctx=json.loads(messages[-1]['content'])
        if not ctx['evidence']:
            return SimpleNamespace(tool_calls=[SimpleNamespace(function=SimpleNamespace(name='knowledge_search',arguments='{"query":"research"}'))])
        if self.after:
            self.after()
        return SimpleNamespace(tool_calls=[SimpleNamespace(function=SimpleNamespace(name='draft_report',arguments=json.dumps({'title':'Research','content':'WITHDRAWN_SECRET_TEXT [1]'})))])


def test_pause_search_withdraw_resume_scrubs_context_and_skips_llm(tmp_path):
    async def scenario():
        store = Store(tmp_path)
        rid = store.create(USERS['researcher'],'Research and save')
        permitted = [True]
        provider = Provider()
        async def tools(name,args,s):
            assert name == 'knowledge_search'
            return {'status':'ok','evidence':[dict(E)],'trace':{'context':E['retrieval_context']}}
        validator = lambda *args: {'valid':permitted[0]}
        engine = Engine(store,provider,tools,validator)
        for _ in range(3):
            result = await engine.advance(rid)
        assert result['state']['evidence']
        assert result['state']['next_node'] == 'planner'
        permitted[0] = False
        before = len(provider.messages)
        result = await Engine(store,provider,tools,validator).run_until_pause(rid)
        assert result['status'] == 'completed'
        assert len(provider.messages) == before
        assert result['state']['evidence'] == []
        assert result['state']['observations'] == []
        assert 'WITHDRAWN_SECRET_TEXT' not in json.dumps(result['state']['args'])
        assert store.get_draft(rid) is None
    asyncio.run(scenario())


def test_withdraw_during_inflight_llm_drops_output(tmp_path):
    async def scenario():
        store=Store(tmp_path); provider=Provider()
        rid=store.create(USERS['researcher'],'Research')
        valid=[True]
        provider.after=lambda: valid.__setitem__(0,False)
        engine=Engine(store,provider,lambda *a:None,lambda *a:{'valid':valid[0]})
        state={'run_id':rid,'owner':'researcher','strategy':'langgraph','request':'Research','spec':{'needs_search':True,'needs_calculation':False},'evidence':[dict(E)],'observations':[{'evidence':[dict(E)]}]}
        result=await engine.node('planner',state)
        assert provider.messages  # dispatched before withdrawal cannot be recalled
        assert result['evidence_invalid'] and result['draft'] == {}
        assert result['observations'] == []
        assert 'WITHDRAWN_SECRET_TEXT' not in json.dumps(result)
    asyncio.run(scenario())


def test_old_approval_cannot_save_after_withdrawal_and_saved_audit_remains(tmp_path,monkeypatch):
    store=Store(tmp_path)
    rid=store.create(USERS['researcher'],'Research')
    store.bind_evidence(rid,[dict(E)],E['retrieval_context'])
    d=store.draft(rid,'Research','WITHDRAWN_SECRET_TEXT [1]')
    store.update(rid,'awaiting_approval',{})
    store.approve(rid,USERS['reviewer'],d['hash'],True)
    monkeypatch.setattr('copilot.evidence.validate_refs',lambda *a:{'valid':False})
    import pytest
    with pytest.raises(PermissionError):
        store.save(rid,USERS['researcher'])
    assert store.get_draft(rid) is None
    with store.db() as c:
        assert c.execute('SELECT count(*) FROM approvals').fetchone()[0] == 0
        assert c.execute('SELECT count(*) FROM reports').fetchone()[0] == 0


def test_missing_provenance_and_offline_validation_fail_closed(monkeypatch):
    from copilot.evidence import validate_refs
    assert not validate_refs([{'text':'legacy'}],'researcher')['valid']
    import requests
    def offline(*a,**kw):
        raise requests.ConnectionError('offline')
    monkeypatch.setattr(requests,'post',offline)
    assert validate_refs([E],'researcher')['status'] == 'validation_unavailable'

def test_saved_report_remains_historical_audit_after_invalidation(tmp_path,monkeypatch):
    store=Store(tmp_path)
    rid=store.create(USERS['researcher'],'Research')
    store.bind_evidence(rid,[dict(E)],E['retrieval_context'])
    draft=store.draft(rid,'Research','Historical report [1]')
    store.update(rid,'awaiting_approval',{})
    store.approve(rid,USERS['reviewer'],draft['hash'],True)
    monkeypatch.setattr('copilot.evidence.validate_refs',lambda *a:{'valid':True})
    saved=store.save(rid,USERS['researcher'])
    original=Path(saved['path']).read_bytes()
    store.invalidate_evidence(rid)
    with store.db() as c:
        report=c.execute('SELECT * FROM reports WHERE run_id=?',(rid,)).fetchone()
        assert report['content']=='Historical report [1]'
        assert report['draft_hash']==draft['hash']
    assert Path(saved['path']).read_bytes()==original


def test_old_observation_is_checked_even_when_last_search_is_valid(tmp_path):
    async def scenario():
        store=Store(tmp_path); provider=Provider()
        rid=store.create(USERS['researcher'],'Research')
        old=dict(E,chunk_uid='withdrawn')
        current=dict(E,chunk_uid='current',text='Current eligible text')
        checked=[]
        def validator(refs,*args):
            checked.extend(r['chunk_uid'] for r in refs)
            return {'valid':all(r['chunk_uid']!='withdrawn' for r in refs)}
        engine=Engine(store,provider,lambda *a:None,validator)
        state={'run_id':rid,'owner':'researcher','strategy':'langgraph','request':'Research',
            'evidence':[current],'observations':[{'evidence':[old]}]}
        result=await engine.node('planner',state)
        assert set(checked)=={'current','withdrawn'}
        assert result['observations']==[] and not provider.messages
    asyncio.run(scenario())


def test_provenance_changes_hash_even_for_identical_draft_content(tmp_path,monkeypatch):
    import pytest
    store=Store(tmp_path)
    rid=store.create(USERS['researcher'],'Research')
    store.bind_evidence(rid,[dict(E)],E['retrieval_context'])
    first=store.draft(rid,'Research','Same visible content [1]')
    store.update(rid,'awaiting_approval',{})
    store.approve(rid,USERS['reviewer'],first['hash'],True)
    store.bind_evidence(rid,[dict(E,revision='r2',chunk_uid='new-uid')],E['retrieval_context'])
    second=store.draft(rid,'Research','Same visible content [1]')
    assert second['hash']!=first['hash']
    with pytest.raises(ValueError):
        store.approve(rid,USERS['reviewer'],first['hash'],True)
    monkeypatch.setattr('copilot.evidence.validate_refs',lambda *a:{'valid':True})
    with pytest.raises(PermissionError):
        store.save(rid,USERS['researcher'])
