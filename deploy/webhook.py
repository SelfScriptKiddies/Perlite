#!/usr/bin/env python3
import hmac, hashlib, os, subprocess
from flask import Flask, request, abort


SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "").encode()
DEPLOY = "./deploy/deploy.sh"

app = Flask(__name__)

def verify(sig_header: str, body: bytes) -> bool:
    if not SECRET:
        return False
    if not sig_header or not sig_header.startswith("sha256="):
        return False
    digest = "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, sig_header)

@app.post("/webhook")
def webhook():
    sig = request.headers.get("X-Hub-Signature-256")
    if not verify(sig, request.data):
        abort(403)
    
    subprocess.Popen([DEPLOY])
    return "ok\n", 200

if __name__ == "__main__":
    app.run("127.0.0.1", 3011)
