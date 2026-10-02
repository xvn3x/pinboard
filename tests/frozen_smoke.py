"""Real end-to-end smoke test of the packaged executable, isolated from user data."""
import json
import os
import subprocess
import time
import argparse
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("url", help="Public board or pin URL to download")
args = parser.parse_args()
home = ROOT / "test-artifacts" / ("frozen-" + str(int(time.time())))
home.mkdir(parents=True)
process = subprocess.Popen([str(ROOT / "Pinboard.exe"), "--no-browser", "--home", str(home)],
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
url = None
headers = {}
try:
    deadline = time.monotonic() + 30
    session_path = home / ".pinboard" / "session.json"
    while not session_path.exists() and time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Packaged app exited: {process.returncode}")
        time.sleep(.3)
    session = json.loads(session_path.read_text(encoding="utf-8"))
    url, key = session["url"].split("#")
    headers = {"X-Pinboard-Key": key}
    html = requests.get(url, timeout=10)
    assert html.status_code == 200
    assert 'class="hero"' not in html.text
    assert 'доску или отдельный пин' in html.content.decode('utf-8')
    assert requests.get(url + "app.js", timeout=10).status_code == 200
    state = requests.get(url + "api/state", headers=headers, timeout=10).json()
    assert state["boards"] == []
    assert state["version"] == "1.1.0"
    response = requests.post(url + "api/start", headers=headers, json={
        "url": args.url,
        "limit": 1, "zip": True}, timeout=10)
    response.raise_for_status()
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        state = requests.get(url + "api/state", headers=headers, timeout=10).json()
        if state["job"]["status"] not in {"starting", "downloading", "packing", "stopping"}:
            break
        time.sleep(.6)
    assert state["job"]["status"] == "complete", state["job"]
    assert state["job"]["count"] >= 1
    assert state["boards"][0]["zip"]
    if "/pin/" in args.url:
        assert state["boards"][0]["source_type"] == "pin"
    board_id = state["boards"][0]["id"]
    archive = requests.get(url + "zip", params={"board": board_id, "key": key}, timeout=10)
    assert archive.content.startswith(b"PK")
    print(json.dumps({"status": "PASS", "packaged_app": True, "downloaded_files": state["job"]["count"],
                      "zip_bytes": len(archive.content)}, indent=2))
finally:
    if url:
        try:
            requests.post(url + "api/stop", headers=headers, json={}, timeout=3)
            time.sleep(1)
            requests.post(url + "api/quit", headers=headers, json={}, timeout=3)
            process.wait(timeout=10)
        except Exception:
            process.terminate()
    elif process.poll() is None:
        process.terminate()
