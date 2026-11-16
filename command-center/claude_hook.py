"""Claude Code hook -> tablet Command Center.

Stop / Notification: send a banner + chime to the tablet (never blocks Claude).
PermissionRequest: show Allow / Deny on the tablet and wait for the answer (up to WAIT seconds).
If the tablet doesn't answer, or the Command Center isn't running, it prints nothing and Claude shows
its normal permission prompt, so this can never lock you out.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

SERVER = "http://127.0.0.1:8765"
WAIT = 45


def call(path, data=None, timeout=3):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(SERVER + path, data=body, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def last_reply(transcript_path, limit=180):
    """Best effort: the start of Claude's last message, for the banner."""
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 200_000))
            lines = f.read().decode("utf-8", "replace").splitlines()
        for line in reversed(lines):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            msg = e.get("message") or {}
            if e.get("type") == "assistant" and isinstance(msg.get("content"), list):
                text = " ".join(c.get("text", "") for c in msg["content"] if c.get("type") == "text").strip()
                if text:
                    text = " ".join(text.split())
                    return text[:limit] + ("…" if len(text) > limit else "")
    except OSError:
        pass
    return ""


def describe(tool, inp):
    if not isinstance(inp, dict):
        return ""
    for key in ("command", "file_path", "url", "pattern", "path", "prompt", "description"):
        if inp.get(key):
            return str(inp[key])[:400]
    return json.dumps(inp)[:400]


def main():
    try:
        ev = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return
    kind = ev.get("hook_event_name", "")
    project = os.path.basename(os.path.normpath(ev.get("cwd") or "")) or "Claude Code"
    try:
        if kind == "Stop":
            call("/claude/event", {"kind": "done", "project": project,
                                   "body": last_reply(ev.get("transcript_path", "")) or "Finished responding."})
        elif kind == "Notification":
            call("/claude/event", {"kind": "notify", "project": project,
                                   "body": ev.get("message") or "Claude needs your attention."})
        elif kind == "PermissionRequest":
            tool = ev.get("tool_name", "a tool")
            ask = call("/claude/ask", {"project": project, "tool": tool,
                                       "detail": describe(tool, ev.get("tool_input")), "wait": WAIT})
            ans = call("/claude/answer?" + urllib.parse.urlencode({"id": ask["id"], "wait": WAIT}),
                       timeout=WAIT + 5)
            if ans.get("decision") in ("allow", "deny"):
                decision = {"behavior": ans["decision"]}
                if ans["decision"] == "deny":
                    decision["message"] = "Denied from the tablet."
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                                         "decision": decision}}))
    except Exception:
        pass   # server not running / timed out: let Claude carry on normally


if __name__ == "__main__":
    main()
