"""HTTP authorization is checked before execution or approval scheduling."""
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api_v2 as api
from copilot.security import USERS, issue
from copilot.store import Store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "store", Store(tmp_path))
    api.active.clear()
    with TestClient(api.app) as client:
        yield client


def headers(name):
    return {"Authorization": "Bearer " + issue(USERS[name])}


def test_http_rejects_unauthenticated_and_forged_identities(client):
    assert client.get("/runs").status_code == 401
    assert client.get("/runs", headers={"Authorization": "Bearer fake"}).status_code == 401
    assert client.post("/login", json={"username": "reviewer", "password": "wrong"}).status_code == 401


def test_cross_workspace_cannot_read_run_or_trace(client):
    r = client.post("/runs", headers=headers("researcher"), json={"request": "Read RRF"}).json()
    assert client.get("/runs/"+r["id"], headers=headers("outsider")).status_code == 403
    assert client.get("/runs/"+r["id"], headers=headers("reviewer")).status_code == 200


def test_http_researcher_cannot_approve_and_stale_draft_is_rejected(client):
    r = client.post("/runs", headers=headers("researcher"), json={"request": "Read RRF and report"}).json()
    rid = r["id"]
    draft = api.store.draft(rid, "RRF", "Report")
    api.store.update(rid, "awaiting_approval", {})
    decision = {"draft_hash": draft["hash"], "approved": True}
    assert client.post(f"/runs/{rid}/approval", headers=headers("researcher"), json=decision).status_code == 403
    api.store.draft(rid, "RRF", "Edited report")
    assert client.post(f"/runs/{rid}/approval", headers=headers("reviewer"), json=decision).status_code == 409


def test_duplicate_approval_after_completion_has_no_new_effect(client):
    r = client.post("/runs", headers=headers("researcher"), json={"request": "Read RRF and report"}).json()
    rid = r["id"]
    api.store.update(rid, "completed", {"answer": "Already done"})
    response = client.post(f"/runs/{rid}/approval", headers=headers("reviewer"), json={"draft_hash": "same", "approved": True})
    assert response.status_code == 200
    with api.store.db() as c:
        assert c.execute("SELECT count(*) FROM reports").fetchone()[0] == 0


def test_one_inflight_action_per_run(client):
    r = client.post("/runs", headers=headers("researcher"), json={"request": "Read RRF"}).json()
    api.active.add(r["id"])
    response = client.post(f'/runs/{r["id"]}/advance', headers=headers("researcher"), json={"continuous": False})
    assert response.status_code == 409
