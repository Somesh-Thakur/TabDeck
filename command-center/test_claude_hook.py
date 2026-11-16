"""End-to-end test of claude_hook.py's Allow/Deny path (taps 'Allow' via the same endpoint the tablet uses)."""
import json
import subprocess
import sys
import time
import urllib.request

S = "http://127.0.0.1:8765"
payload = {"hook_event_name": "PermissionRequest", "cwd": r"D:\Lenovo Tab M10 project",
           "tool_name": "Bash", "tool_input": {"command": "echo hello from the hook test"}}
p = subprocess.Popen([sys.executable, "claude_hook.py"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
p.stdin.write(json.dumps(payload))
p.stdin.close()

aid = None
for _ in range(30):
    time.sleep(0.2)
    asks = json.loads(urllib.request.urlopen(S + "/status").read())["claude_asks"]
    if asks:
        aid = asks[0]
        break
print("card shown on tablet, id:", aid)
time.sleep(4)   # leave it on screen for a moment
req = urllib.request.Request(S + "/claude/reply", data=json.dumps({"id": aid, "decision": "allow"}).encode(), method="POST")
print("tap Allow ->", json.loads(urllib.request.urlopen(req).read()))
out = p.stdout.read()
p.wait()
print("hook told Claude:", out.strip())
