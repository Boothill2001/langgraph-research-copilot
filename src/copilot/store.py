"""Canonical reports are transactional; file export is deterministic and recoverable."""
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile
import time
import uuid

from .security import VAR


def digest(content):
    return sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Store:
    def __init__(self, root=None):
        self.root = Path(root or VAR)
        self.root.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.executescript('''
              CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,owner TEXT,workspace TEXT,request TEXT,strategy TEXT,status TEXT,state TEXT,created REAL);
              CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT,node TEXT,input TEXT,output TEXT,elapsed_ms REAL,created REAL);
              CREATE TABLE IF NOT EXISTS drafts(run_id TEXT PRIMARY KEY,title TEXT,content TEXT,hash TEXT);
              CREATE TABLE IF NOT EXISTS approvals(run_id TEXT PRIMARY KEY,draft_hash TEXT,reviewer TEXT,approved INTEGER,created REAL);
              CREATE TABLE IF NOT EXISTS reports(action_id TEXT PRIMARY KEY,run_id TEXT UNIQUE,report_id TEXT UNIQUE,title TEXT,content TEXT,draft_hash TEXT,created REAL);
              CREATE TABLE IF NOT EXISTS evidence_bindings(run_id TEXT PRIMARY KEY,refs TEXT,context TEXT,stale INTEGER DEFAULT 0);
              CREATE TABLE IF NOT EXISTS api_calls(id TEXT PRIMARY KEY,run_id TEXT,status TEXT,reserved REAL,cost REAL,usage TEXT,created REAL);
            ''')

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.root / "copilot.sqlite", timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def create(self, user, request, strategy="langgraph"):
        rid = uuid.uuid4().hex
        with self.db() as c:
            c.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)", (rid, user["sub"], user["workspace"], request, strategy, "new", "{}", time.time()))
        return rid

    def run(self, rid):
        with self.db() as c:
            row = c.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
            if row is None:
                raise KeyError("Unknown run")
            result = dict(row)
            result["state"] = json.loads(result["state"])
            return result

    def update(self, rid, status, state):
        with self.db() as c:
            c.execute("UPDATE runs SET status=?,state=? WHERE id=?", (status, json.dumps(state, ensure_ascii=False), rid))

    def event(self, rid, node, inputs, outputs, elapsed_ms):
        with self.db() as c:
            c.execute("INSERT INTO events(run_id,node,input,output,elapsed_ms,created) VALUES(?,?,?,?,?,?)",
                      (rid, node, json.dumps(inputs, ensure_ascii=False), json.dumps(outputs, ensure_ascii=False), elapsed_ms, time.time()))

    def events(self, rid):
        with self.db() as c:
            return [{**dict(r), "input": json.loads(r["input"]), "output": json.loads(r["output"])}
                    for r in c.execute("SELECT * FROM events WHERE run_id=? ORDER BY id", (rid,))]

    def draft(self, rid, title, content):
        value = {"title": title, "content": content, "destination": "reports/" + rid + ".md"}
        binding = self.evidence_binding(rid)
        if binding:
            value["evidence_sha256"] = digest({"refs": json.loads(binding["refs"]), "context": json.loads(binding["context"])})
        hashed = digest(value)
        with self.db() as c:
            old = c.execute("SELECT hash FROM drafts WHERE run_id=?", (rid,)).fetchone()
            if old and old["hash"] != hashed:
                c.execute("DELETE FROM approvals WHERE run_id=?", (rid,))
            c.execute("INSERT OR REPLACE INTO drafts VALUES(?,?,?,?)", (rid, title, content, hashed))
        return {**value, "hash": hashed}

    def get_draft(self, rid):
        with self.db() as c:
            d = c.execute("SELECT * FROM drafts WHERE run_id=?", (rid,)).fetchone()
            return dict(d) if d else None

    def approve(self, rid, user, draft_hash, approved):
        run = self.run(rid)
        if user["role"] != "reviewer" or user["workspace"] != run["workspace"]:
            raise PermissionError("A reviewer from the same workspace must decide")
        if run["status"] != "awaiting_approval":
            raise ValueError("Run is not waiting for approval")
        with self.db() as c:
            draft = c.execute("SELECT * FROM drafts WHERE run_id=?", (rid,)).fetchone()
            if not draft or draft["hash"] != draft_hash:
                raise ValueError("Draft changed; review the current content")
            c.execute("INSERT OR REPLACE INTO approvals VALUES(?,?,?,?,?)", (rid, draft_hash, user["sub"], int(approved), time.time()))

    def save(self, rid, user, crash_after_commit=False):
        binding = self.evidence_binding(rid)
        if binding:
            from .evidence import validate_bound
            checked = validate_bound(json.loads(binding["refs"]), user["sub"], json.loads(binding["context"]))
            if binding["stale"] or not checked["valid"]:
                self.invalidate_evidence(rid)
                raise PermissionError("Evidence changed; retrieve, draft and approve again")
        action_id = rid + ":save:v1"
        run = self.run(rid)
        if user["sub"] != run["owner"] or user["workspace"] != run["workspace"]:
            raise PermissionError("Save must execute in the run owner's identity")
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            d = c.execute("SELECT * FROM drafts WHERE run_id=?", (rid,)).fetchone()
            a = c.execute("SELECT * FROM approvals WHERE run_id=?", (rid,)).fetchone()
            current_binding = c.execute("SELECT * FROM evidence_bindings WHERE run_id=?", (rid,)).fetchone()
            if d and current_binding:
                expected = {"title":d["title"],"content":d["content"],"destination":"reports/"+rid+".md",
                            "evidence_sha256":digest({"refs":json.loads(current_binding["refs"]),"context":json.loads(current_binding["context"])})}
                if current_binding["stale"] or digest(expected) != d["hash"]:
                    raise PermissionError("Draft provenance changed; rebuild and approve the draft")
            if not d or not a or not a["approved"] or a["draft_hash"] != d["hash"]:
                raise PermissionError("Exact draft has no valid approval")
            c.execute("INSERT OR IGNORE INTO reports VALUES(?,?,?,?,?,?,?)",
                      (action_id, rid, rid, d["title"], d["content"], d["hash"], time.time()))
            report = dict(c.execute("SELECT * FROM reports WHERE action_id=?", (action_id,)).fetchone())
            if report["draft_hash"] != d["hash"]:
                raise ValueError("An action ID cannot save a different draft")
        if crash_after_commit:
            raise RuntimeError("Injected crash after canonical commit, before export")
        folder = self.root / "reports"
        folder.mkdir(exist_ok=True)
        path = folder / (rid + ".md")
        desired = "# " + report["title"] + "\n\n" + report["content"] + "\n"
        if not path.exists() or path.read_text(encoding="utf-8") != desired:
            with NamedTemporaryFile("w", encoding="utf-8", dir=folder, prefix=rid + "-", suffix=".partial", delete=False) as output:
                temporary = Path(output.name)
                output.write(desired)
            try:
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        return {"status": "saved", "report_id": rid, "action_id": action_id,
                "draft_hash": report["draft_hash"], "path": str(path), "content": report["content"]}

    def bind_evidence(self, rid, evidence, context):
        refs, ctx = json.dumps(evidence), json.dumps(context)
        with self.db() as c:
            old = c.execute("SELECT * FROM evidence_bindings WHERE run_id=?", (rid,)).fetchone()
            if old and (old["refs"] != refs or old["context"] != ctx):
                c.execute("DELETE FROM approvals WHERE run_id=?", (rid,))
            c.execute("INSERT OR REPLACE INTO evidence_bindings VALUES(?,?,?,0)", (rid, refs, ctx))

    def evidence_binding(self, rid):
        with self.db() as c:
            row = c.execute("SELECT * FROM evidence_bindings WHERE run_id=?", (rid,)).fetchone()
            return dict(row) if row else None

    def invalidate_evidence(self, rid):
        with self.db() as c:
            c.execute("DELETE FROM approvals WHERE run_id=?", (rid,))
            c.execute("DELETE FROM drafts WHERE run_id=?", (rid,))
            c.execute("UPDATE evidence_bindings SET stale=1 WHERE run_id=?", (rid,))

    def reserve(self, rid, maximum, limit=5.):
        call_id = uuid.uuid4().hex
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            spent = c.execute("SELECT COALESCE(SUM(COALESCE(cost,reserved)),0) FROM api_calls").fetchone()[0]
            if spent + maximum > limit:
                raise RuntimeError("API budget reached; no new provider call")
            c.execute("INSERT INTO api_calls VALUES(?,?,?,?,?,?,?)", (call_id, rid, "reserved", maximum, None, "{}", time.time()))
        return call_id

    def settle(self, call_id, usage, cost):
        with self.db() as c:
            c.execute("UPDATE api_calls SET status='complete',cost=?,usage=? WHERE id=?", (cost, json.dumps(usage), call_id))
