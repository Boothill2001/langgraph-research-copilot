"""Local end-to-end checks with a real provider, real MCP and an actual API process restart."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from copilot.store import Store
from copilot.security import USERS

API = "http://127.0.0.1:8529"


def login(name):
    r = requests.post(API + "/login", json={"username": name, "password": os.getenv("COPILOT_DEMO_PASSWORD", "learn-local-only")}, timeout=10)
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"]}


def wait(rid, headers):
    for _ in range(150):
        r = requests.get(API + "/runs/" + rid, headers=headers, timeout=10)
        r.raise_for_status()
        run = r.json()
        if run["status"] != "running":
            return run
        time.sleep(.5)
    raise TimeoutError("Run did not reach a stable boundary")


def main(pid):
    h = login("researcher")
    r = requests.post(API + "/runs", headers=h, json={"request": "Find how RRF combines rankings in source rrf, calculate 1/(60+1) + 1/(60+3), and save a short cited report."}, timeout=10)
    r.raise_for_status()
    rid = r.json()["id"]
    requests.post(API + f"/runs/{rid}/advance", headers=h, json={"continuous": True}, timeout=10).raise_for_status()
    pending = wait(rid, h)
    assert pending["status"] == "awaiting_approval", pending["state"]
    denied = requests.post(API + f"/runs/{rid}/approval", headers=h, json={"draft_hash": pending["draft"]["hash"], "approved": True}, timeout=10)
    assert denied.status_code == 403
    before_tools = sum(e["node"] == "tools" for e in pending["events"])
    before_calls = 0
    store = Store()
    with store.db() as c:
        before_calls = c.execute("SELECT count(*) FROM api_calls WHERE run_id=?", (rid,)).fetchone()[0]
    if os.name == "nt":
        command = f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}'; if ($p.CommandLine -notlike '*api_v2:app*') {{ throw 'PID is not the test API' }}; Stop-Process -Id {int(pid)}"
        subprocess.run(["powershell", "-NoProfile", "-Command", command], check=True, capture_output=True)
    else:
        raise RuntimeError("This process-restart harness currently targets the Windows development setup")
    with (ROOT / "var/agent-restart-check.log").open("ab") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "api_v2:app", "--host", "127.0.0.1", "--port", "8529"],
                    cwd=ROOT, env={**os.environ, "RAG_API_URL": "http://127.0.0.1:8011"}, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
    (ROOT / "var/agent.pid").write_text(str(process.pid))
    for _ in range(60):
        try:
            if requests.get(API + "/health", timeout=1).ok:
                break
        except requests.RequestException:
            pass
        time.sleep(.5)
    reviewer = login("reviewer")
    recovered = requests.get(API + "/runs/" + rid, headers=reviewer, timeout=10).json()
    assert recovered["draft"]["hash"] == pending["draft"]["hash"]
    decision = {"draft_hash": recovered["draft"]["hash"], "approved": True}
    requests.post(API + f"/runs/{rid}/approval", headers=reviewer, json=decision, timeout=10).raise_for_status()
    final = wait(rid, reviewer)
    assert final["status"] == "completed" and final["state"].get("saved"), final["state"]
    assert sum(e["node"] == "tools" for e in final["events"]) == before_tools
    repeated = requests.post(API + f"/runs/{rid}/approval", headers=reviewer, json=decision, timeout=10)
    assert repeated.status_code == 200
    with store.db() as c:
        reports = c.execute("SELECT count(*) FROM reports WHERE run_id=?", (rid,)).fetchone()[0]
        after_calls = c.execute("SELECT count(*) FROM api_calls WHERE run_id=?", (rid,)).fetchone()[0]
    assert reports == 1 and before_calls == after_calls
    report = {"mode": "real local HTTP/API process restart, real DeepSeek and real MCP tools", "run_id": rid,
              "researcher_approval_http": denied.status_code, "draft_hash_unchanged": True,
              "read_tools_before_after": [before_tools, before_tools], "llm_calls_before_after": [before_calls, after_calls],
              "canonical_report_count": reports, "repeated_approval_http": repeated.status_code,
              "new_process_id": process.pid, "passed": True}
    (ROOT / "artifacts/live-verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restart-pid", type=int, required=True, help="PID of the development API process this task started")
    main(parser.parse_args().restart_pid)
