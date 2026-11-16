"""Adds TabDeck's Claude Code hooks to ~/.claude/settings.json (merging, never replacing what's there)."""
import json
import os
import sys
from pathlib import Path

settings_path = Path.home() / ".claude" / "settings.json"
hook = {"type": "command", "command": sys.executable.replace("\\", "/"),
        "args": [str(Path(__file__).with_name("claude_hook.py")).replace("\\", "/")]}
wanted = {
    "Stop": {"hooks": [{**hook, "timeout": 10}]},
    "Notification": {"hooks": [{**hook, "timeout": 10}]},
    "PermissionRequest": {"matcher": "*", "hooks": [{**hook, "timeout": 55,
                                                     "statusMessage": "Waiting for an answer on the tablet…"}]},
}

data = {}
if settings_path.exists():
    data = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
    settings_path.with_suffix(".json.bak").write_text(json.dumps(data, indent=2), encoding="utf-8")
hooks = data.setdefault("hooks", {})
for event, entry in wanted.items():
    lst = hooks.setdefault(event, [])
    if not any("claude_hook.py" in json.dumps(e) for e in lst):   # don't add twice
        lst.append(entry)
settings_path.parent.mkdir(parents=True, exist_ok=True)
settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
print(f"Hooks added to {settings_path} (backup: settings.json.bak). Start a new Claude Code session to use them.")
