"""Start only missing local services, wait for readiness, then open the workspace."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parent
RAG = ROOT.parent / "RAG_project"
VAR = ROOT / "var"


def ready(url):
    try:
        with urlopen(url, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def launch(no_browser=False):
    VAR.mkdir(exist_ok=True)
    sys.path.insert(0, str(ROOT / "src"))
    from copilot.security import SECRET_FILE
    env = {**os.environ, "COPILOT_SECRET_FILE": str(SECRET_FILE), "RAG_API_URL": "http://127.0.0.1:8011", "COPILOT_API_URL": "http://127.0.0.1:8529"}
    services = [
        ("evidence", RAG, ["-m", "uvicorn", "api.research_app:app", "--host", "127.0.0.1", "--port", "8011"], "http://127.0.0.1:8011/research/health"),
        ("agent", ROOT, ["-m", "uvicorn", "api_v2:app", "--host", "127.0.0.1", "--port", "8529"], "http://127.0.0.1:8529/health"),
        ("workspace", ROOT, ["-m", "streamlit", "run", "workspace.py", "--server.port", "8530", "--server.address", "127.0.0.1", "--server.headless", "true"], "http://127.0.0.1:8530/_stcore/health"),
    ]
    if not (RAG / "data/research/chunks.json").exists():
        print("Preparing the real documentation corpus and local embedding index...", flush=True)
        python = RAG / ".venv/Scripts/python.exe" if os.name == "nt" else RAG / ".venv/bin/python"
        subprocess.run([str(python), "scripts/ingest_research.py"], cwd=RAG, env=env, check=True)
        subprocess.run([str(python), "scripts/evaluate_research.py"], cwd=RAG, env=env, check=True)
    for name, folder, args, url in services:
        if ready(url):
            print(name + " is ready.", flush=True)
            continue
        # Do not terminate or attach to a different program occupying our port.
        port = int(url.split(":")[2].split("/")[0])
        with socket.socket() as test:
            if test.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"Port {port} is occupied by a service that is not ready. Inspect it before restarting; nothing was stopped.")
        python = folder / ".venv/Scripts/python.exe" if os.name == "nt" else folder / ".venv/bin/python"
        if not python.exists():
            raise RuntimeError("Missing environment in " + str(folder) + ". Follow the setup instructions in README.")
        with (VAR / (name + ".log")).open("ab") as log:
            process = subprocess.Popen([str(python), *args], cwd=folder, env=env, stdout=log, stderr=log,
                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        (VAR / (name + ".pid")).write_text(str(process.pid))
        deadline = time.monotonic() + 180
        while not ready(url):
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(name + " did not become ready; inspect var/" + name + ".log")
            time.sleep(.5)
        print(name + " is ready.", flush=True)
    if not no_browser:
        webbrowser.open("http://127.0.0.1:8530")
    print("Research Copilot: http://127.0.0.1:8530", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-browser", action="store_true")
    launch(parser.parse_args().no_browser)
