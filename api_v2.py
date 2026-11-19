"""Local authenticated API: background execution, durable traces and reviewer decisions."""
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from copilot.engine import Engine
from copilot.security import login, verify
from copilot.store import Store

app = FastAPI(title="Research Copilot", version="2.0")
store = Store()
active = set()


def principal(authorization: str = Header(default="")):
    try:
        if not authorization.startswith("Bearer "):
            raise ValueError("Bearer identity required")
        return verify(authorization[7:])
    except (ValueError, KeyError):
        raise HTTPException(401, "Invalid or expired identity")


def accessible(rid, user):
    try:
        r = store.run(rid)
    except KeyError:
        raise HTTPException(404, "Run unavailable")
    if r["owner"] != user["sub"] and not (user["role"] == "reviewer" and user["workspace"] == r["workspace"]):
        raise HTTPException(403, "Run unavailable to this identity")
    return r


class Credentials(BaseModel):
    username: str
    password: str


@app.post("/login")
def authenticate(request: Credentials):
    try:
        token = login(request.username, request.password)
        claims = verify(token)
        return {"token": token, "user": {k: claims[k] for k in ("sub", "role", "workspace")}}
    except ValueError:
        raise HTTPException(401, "Invalid demo credentials")


@app.get("/health")
def health():
    return {"status": "ready", "version": "2.0", "active_runs": len(active)}


class NewRun(BaseModel):
    request: str = Field(min_length=3, max_length=2000)
    strategy: str = "langgraph"


@app.post("/runs")
def create(request: NewRun, user=Depends(principal)):
    if request.strategy not in ("langgraph", "function_loop", "workflow"):
        raise HTTPException(422, "Unknown strategy")
    rid = store.create(user, request.request, request.strategy)
    return store.run(rid)


@app.get("/runs")
def runs(user=Depends(principal)):
    with store.db() as c:
        rows = c.execute("SELECT id,owner,request,status,strategy,created FROM runs WHERE owner=? OR (workspace=? AND ?='reviewer') ORDER BY created DESC LIMIT 100",
                         (user["sub"], user["workspace"], user["role"])).fetchall()
    return [dict(r) for r in rows]


@app.get("/runs/{rid}")
def get_run(rid: str, user=Depends(principal)):
    r = accessible(rid, user)
    if r["status"] == "running" and rid not in active:
        store.update(rid, "recoverable", r["state"])
        r = store.run(rid)
    r["events"] = store.events(rid)
    r["draft"] = store.get_draft(rid)
    if rid in active:
        r["status"] = "running"
    return r


async def execute(rid, continuous, resume=None):
    try:
        engine = Engine(store)
        if continuous:
            await engine.run_until_pause(rid, resume)
        else:
            await engine.advance(rid, resume)
    except Exception as exc:
        r = store.run(rid)
        store.update(rid, "error", {**r["state"], "error": type(exc).__name__ + ": " + str(exc)[:500]})
    finally:
        active.discard(rid)


def schedule(rid, continuous, resume=None):
    if rid in active:
        raise HTTPException(409, "Run is already processing")
    active.add(rid)
    r = store.run(rid)
    store.update(rid, "running", r["state"])
    task = asyncio.create_task(execute(rid, continuous, resume))
    # Keep a strong reference and consume unexpected task errors.
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    return {"run_id": rid, "status": "running"}


TASKS = set()


class Advance(BaseModel):
    continuous: bool = False


@app.post("/runs/{rid}/advance")
async def advance(rid: str, request: Advance, user=Depends(principal)):
    r = accessible(rid, user)
    if r["owner"] != user["sub"]:
        raise HTTPException(403, "Only the request owner executes the workflow")
    if r["status"] in ("completed", "awaiting_approval"):
        raise HTTPException(409, "Run completed or requires reviewer approval")
    return schedule(rid, request.continuous)


class Decision(BaseModel):
    draft_hash: str
    approved: bool
    continuous: bool = True


@app.post("/runs/{rid}/approval")
async def approval(rid: str, request: Decision, user=Depends(principal)):
    r = accessible(rid, user)
    if r["status"] == "completed":
        if user["role"] != "reviewer":
            raise HTTPException(403, "Reviewer required")
        return {"run_id": rid, "status": "completed", "note": "Already finalized; no repeated write"}
    if rid in active:
        raise HTTPException(409, "Run already processing")
    try:
        store.approve(rid, user, request.draft_hash, request.approved)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return schedule(rid, request.continuous, {"approved": request.approved})


class DraftEdit(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=10000)


@app.patch("/runs/{rid}/draft")
async def edit_draft(rid: str, request: DraftEdit, user=Depends(principal)):
    r = accessible(rid, user)
    if r["owner"] != user["sub"] or r["status"] != "awaiting_approval" or rid in active:
        raise HTTPException(409, "Only an idle, pending draft can be edited by its owner")
    draft = store.draft(rid, request.title, request.content)
    state = {**r["state"], "draft": draft}
    if r["strategy"] == "langgraph":
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        async with AsyncSqliteSaver.from_conn_string(str(store.root / "graph.sqlite")) as saver:
            await Engine(store).graph(saver).aupdate_state({"configurable": {"thread_id": rid}}, {"draft": draft})
    store.update(rid, "awaiting_approval", state)
    return {"draft": draft, "notice": "Previous approval invalidated; review this exact content again"}


@app.get("/monitoring")
def monitoring(user=Depends(principal)):
    with store.db() as c:
        ids = [r[0] for r in c.execute("SELECT id FROM runs WHERE workspace=?", (user["workspace"],))]
        rows = [dict(r) for r in c.execute("SELECT id,status,strategy,state FROM runs WHERE workspace=?", (user["workspace"],))]
        events = [dict(r) for r in c.execute("SELECT run_id,node,elapsed_ms,output FROM events") if r["run_id"] in ids]
        calls = [dict(r) for r in c.execute("SELECT run_id,status,cost,reserved,usage FROM api_calls") if r["run_id"] in ids]
        decisions = [dict(r) for r in c.execute("SELECT a.run_id,a.approved FROM approvals a JOIN runs r ON r.id=a.run_id WHERE r.workspace=?", (user["workspace"],))]
    outputs = [json.loads(e["output"]) for e in events]
    tool_outputs = [json.loads(e["output"]).get("observations", [])[-1] for e in events
                    if e["node"] == "tools" and json.loads(e["output"]).get("observations")]
    metrics = {"evidence_rejections": sum(o.get("status") == "insufficient_evidence" for o in tool_outputs),
               "permission_denials": sum(o.get("status") == "forbidden" for o in tool_outputs),
               "approved": sum(bool(d["approved"]) for d in decisions), "rejected": sum(not d["approved"] for d in decisions),
               "node_errors": sum(bool(o.get("error")) and o.get("error") != "GraphInterrupt" for o in outputs),
               "input_tokens": sum(json.loads(c["usage"]).get("prompt_tokens", 0) for c in calls),
               "output_tokens": sum(json.loads(c["usage"]).get("completion_tokens", 0) for c in calls)}
    return {"scope": "Measured local executions, not production traffic", "runs": rows, "events": events, "calls": calls, "metrics": metrics}
