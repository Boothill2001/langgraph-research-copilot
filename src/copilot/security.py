"""Local demo login and signed service identity. This is not enterprise SSO."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time

ROOT = Path(__file__).resolve().parents[2]
VAR = Path(os.getenv("COPILOT_VAR", str(ROOT / "var")))
VAR.mkdir(parents=True, exist_ok=True)
SECRET_FILE = Path(os.getenv("COPILOT_SECRET_FILE", str(VAR / "secret.key")))
if not SECRET_FILE.exists():
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with SECRET_FILE.open("xb") as f:
            f.write(secrets.token_bytes(48))
    except FileExistsError:
        pass
os.environ["COPILOT_SECRET_FILE"] = str(SECRET_FILE)

USERS = {"curator": {"sub": "curator", "role": "curator", "workspace": "research"},"researcher": {"sub": "researcher", "role": "researcher", "workspace": "research"},
         "reviewer": {"sub": "reviewer", "role": "reviewer", "workspace": "research"},
         "outsider": {"sub": "outsider", "role": "researcher", "workspace": "other"}}


def issue(principal, ttl=28800):
    encode = lambda x: base64.urlsafe_b64encode(x).rstrip(b"=").decode()
    head = encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = encode(json.dumps({**principal, "aud": "research-copilot", "exp": time.time() + ttl}).encode())
    signature = hmac.new(SECRET_FILE.read_bytes(), (head + "." + body).encode(), hashlib.sha256).digest()
    return head + "." + body + "." + encode(signature)


def verify(token):
    head, body, sig = token.split(".")
    decode = lambda x: base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))
    if json.loads(decode(head)) != {"alg": "HS256", "typ": "JWT"}:
        raise ValueError("Invalid algorithm")
    expected = hmac.new(SECRET_FILE.read_bytes(), (head + "." + body).encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, decode(sig)):
        raise ValueError("Invalid signature")
    claims = json.loads(decode(body))
    if claims.get("exp", 0) <= time.time() or claims.get("aud") != "research-copilot":
        raise ValueError("Expired token or wrong audience")
    if {k: claims.get(k) for k in ("sub", "role", "workspace")} != USERS.get(claims.get("sub")):
        raise ValueError("Identity revoked or unknown")
    return claims


def login(username, password):
    expected = os.getenv("COPILOT_DEMO_PASSWORD", "learn-local-only")
    if username not in USERS or not hmac.compare_digest(password.encode(), expected.encode()):
        raise ValueError("Invalid demo credentials")
    return issue(USERS[username])
