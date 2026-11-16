"""Tab Command Center - laptop side (built to be as light as possible).

* Zero polling of the tablet: listens to adb's own device-tracking socket.
* GPU read in-process through NVML (no nvidia-smi processes).
* Stats are only collected while the tablet page is connected.
* Everything travels over USB (adb reverse); nothing uses Wi-Fi.

Run:  pythonw server.py
"""
import ctypes
import hashlib
import json
import os
import queue
import socket
import subprocess
import threading
import time
from ctypes import byref, c_uint, c_ulonglong, c_void_p, Structure
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent
WEB, ICONS = ROOT / "web", ROOT / "icons"
APPS_FILE = ROOT / "apps.json"
PORT = 8765
TOOLS = ROOT.parent / "tools"
ADB = TOOLS / "platform-tools" / "adb.exe"
SCRCPY = TOOLS / "scrcpy" / "scrcpy.exe"
NO_WINDOW = 0x08000000
DEFAULT_APPS = ["Google Chrome", "Brave", "Discord", "WhatsApp", "Visual Studio Code", "Steam",
                "OBS Studio", "Claude", "File Explorer", "Terminal", "Settings", "Notepad"]

SETTINGS_FILE = ROOT / "settings.json"
STARTUP_LNK = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup\Command Center.lnk"
DEFAULT_SETTINGS = {
    "widgets": [{"id": w, "on": True} for w in ("perf", "gpu", "net", "media", "mic")],
    "dock": ["lock", "snip", "taskmgr", "desktop"],
    "wallpaper": "aurora", "accent": "blue", "clock24": False, "show_date": True,
    "sound": True, "volume": 0.6, "banner_secs": 6,
    "interval": 1, "brightness": None, "mic_source": "mic-voice-communication",
    "mic_on": False,   # remembered so the mic comes back after a restart / replug
    "display_mirror": False,   # second screen: False = extend (new screen), True = mirror the laptop
    "tab_speaker": False,      # play the laptop's sound on the tablet speakers
    "speaker_mute_laptop": True,
}
DISPLAY = None
SPEAKER = None
NOW_PLAYING = None
MIC_SOURCES = {"mic-voice-communication", "mic", "mic-camcorder", "mic-unprocessed"}

lock = threading.Lock()
subscribers: list[queue.Queue] = []
state = {"tablet": False, "mic": {"on": False, "available": SCRCPY.exists()}, "notes": []}
ICONS.mkdir(exist_ok=True)


def load_settings():
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        s.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
    except (OSError, json.JSONDecodeError):
        pass
    known = {w["id"] for w in s["widgets"]}   # keep new widgets visible after upgrades
    s["widgets"] += [w for w in DEFAULT_SETTINGS["widgets"] if w["id"] not in known]
    return s


settings = load_settings()


def update_settings(patch):
    global settings
    s = dict(settings)
    for k, v in patch.items():
        if k not in DEFAULT_SETTINGS:
            continue
        if k == "interval":
            v = min(10, max(1, int(v)))
        elif k == "volume":
            v = min(1.0, max(0.0, float(v)))
        elif k == "brightness" and v is not None:
            v = min(255, max(5, int(v)))
        elif k == "mic_source" and v not in MIC_SOURCES:
            continue
        s[k] = v
    settings = s
    SETTINGS_FILE.write_text(json.dumps(s, indent=1), encoding="utf-8")
    broadcast("settings", s)
    if "brightness" in patch and state["tablet"]:
        threading.Thread(target=apply_brightness, daemon=True).start()
    if ("tab_speaker" in patch or "speaker_mute_laptop" in patch) and SPEAKER:
        SPEAKER.changed()
    if "mic_source" in patch and state["mic"]["on"]:
        threading.Thread(target=mic, args=(True, "mode changed"), daemon=True).start()
    return s


def display_driver_installed():
    try:
        import display
        return display.ParsecVDD.installed()
    except Exception:
        return False


def apply_brightness():
    b = settings.get("brightness")
    if b is None:
        run([str(ADB), "shell", "settings put system screen_brightness_mode 1"])   # automatic
    else:
        run([str(ADB), "shell", f"settings put system screen_brightness_mode 0; "
                                f"settings put system screen_brightness {int(b)}"])


def set_autostart(on):
    if on:
        exe = Path(os.__file__).resolve().parent.parent / "pythonw.exe"
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
              "$s.TargetPath=$env:EXE;$s.Arguments='\"'+$env:SRV+'\"';$s.WorkingDirectory=$env:DIR;"
              "$s.WindowStyle=7;$s.Description='Tab Command Center';$s.Save()")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=NO_WINDOW, timeout=20,
                       env={**os.environ, "LNK": str(STARTUP_LNK), "EXE": str(exe),
                            "SRV": str(ROOT / "server.py"), "DIR": str(ROOT)})
    elif STARTUP_LNK.exists():
        STARTUP_LNK.unlink()
    return STARTUP_LNK.exists()


def run(cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              creationflags=NO_WINDOW).stdout
    except Exception:
        return ""


def broadcast(kind, data):
    msg = f"event: {kind}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()
    for q in list(subscribers):
        try:
            q.put_nowait(msg)
        except queue.Full:
            pass


# ------------------------------------------------------------------ GPU (NVML)
class _Util(Structure):
    _fields_ = [("gpu", c_uint), ("mem", c_uint)]


class _Mem(Structure):
    _fields_ = [("total", c_ulonglong), ("free", c_ulonglong), ("used", c_ulonglong)]


class GPU:
    def __init__(self):
        self.h = None
        try:
            self.nv = ctypes.WinDLL("nvml.dll")
            if self.nv.nvmlInit_v2() == 0:
                h = c_void_p()
                if self.nv.nvmlDeviceGetHandleByIndex_v2(0, byref(h)) == 0:
                    self.h = h
                    buf = ctypes.create_string_buffer(64)
                    self.nv.nvmlDeviceGetName(h, buf, 64)
                    self.name = buf.value.decode().replace("NVIDIA GeForce ", "")
        except OSError:
            pass

    def read(self):
        if not self.h:
            return None
        t, p, u, m = c_uint(), c_uint(), _Util(), _Mem()
        self.nv.nvmlDeviceGetTemperature(self.h, 0, byref(t))
        self.nv.nvmlDeviceGetPowerUsage(self.h, byref(p))
        self.nv.nvmlDeviceGetUtilizationRates(self.h, byref(u))
        self.nv.nvmlDeviceGetMemoryInfo(self.h, byref(m))
        return {"name": self.name, "t": t.value, "w": round(p.value / 1000, 1), "u": u.gpu,
                "vu": round(m.used / 2**30, 1), "vt": round(m.total / 2**30)}


def trim_memory():
    """Give pages we aren't actively using back to Windows (start-up code, NVML init, etc.)."""
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = c_void_p
    ctypes.windll.psapi.EmptyWorkingSet.argtypes = [c_void_p]
    ctypes.windll.psapi.EmptyWorkingSet(k.GetCurrentProcess())


# ------------------------------------------------------------------ stats
def stats_loop():
    gpu = GPU()
    g, last, last_gpu, last_trim = None, None, 0.0, time.monotonic() - 100   # first trim ~20 s after start
    while True:
        time.sleep(settings["interval"])
        if time.monotonic() - last_trim > 120:
            trim_memory()
            last_trim = time.monotonic()
        if not subscribers:           # nobody watching -> do nothing at all
            last = None
            time.sleep(4)
            continue
        net, now = psutil.net_io_counters(), time.monotonic()
        if now - last_gpu >= 3 or g is None:  # GPU at most every 3 s keeps the dGPU from being nagged
            g, last_gpu = gpu.read(), now
        vm, bat = psutil.virtual_memory(), psutil.sensors_battery()
        s = {"c": round(psutil.cpu_percent()), "r": round(vm.percent), "ru": round(vm.used / 2**30, 1),
             "rt": round(vm.total / 2**30), "g": g, "b": bat and [round(bat.percent), bat.power_plugged]}
        if last:
            dt = now - last[1]
            s["d"] = round((net.bytes_recv - last[0].bytes_recv) / dt)
            s["u"] = round((net.bytes_sent - last[0].bytes_sent) / dt)
        last = (net, now)
        broadcast("s", s)


def discord_watch():
    """Is Discord running? Cheap: re-checks one cached PID; a full process scan only while it's closed."""
    pid, running = None, False
    while True:
        time.sleep(5)
        if not subscribers:
            continue
        now = False
        if pid and psutil.pid_exists(pid):
            try:
                now = psutil.Process(pid).name().lower() == "discord.exe"
            except psutil.Error:
                now = False
        if not now:
            pid = next((p.pid for p in psutil.process_iter(["name"])
                        if (p.info["name"] or "").lower() == "discord.exe"), None)
            now = pid is not None
        if now != running:
            running = now
            state["discord"] = running
            broadcast("discord", running)


# ------------------------------------------------------------------ tablet (event driven)
def _recvn(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError
        buf += chunk
    return buf


def tidy_chrome_tabs():
    """Keep exactly one dashboard tab in Chrome on the tablet (closes stale duplicates).
    Returns True if one is already open."""
    import urllib.request
    adb = str(ADB)
    run([adb, "forward", "tcp:9333", "localabstract:chrome_devtools_remote"])
    try:
        with urllib.request.urlopen("http://127.0.0.1:9333/json", timeout=3) as r:
            pages = [p for p in json.loads(r.read()) if p.get("type") == "page"]
        mine = [p for p in pages if f"localhost:{PORT}" in p.get("url", "") and "preview" not in p.get("url", "")]
        for p in mine[1:]:
            urllib.request.urlopen(f"http://127.0.0.1:9333/json/close/{p['id']}", timeout=3).read()
        if mine:
            urllib.request.urlopen(f"http://127.0.0.1:9333/json/activate/{mine[0]['id']}", timeout=3).read()
        return bool(mine)
    except Exception:
        return False
    finally:
        run([adb, "forward", "--remove", "tcp:9333"])


last_tap = 0.0


def tap_for_fullscreen():
    """A real touch on an inert spot (the clock / rings area): Android only allows full screen
    and sound after a user gesture."""
    global last_tap
    if time.monotonic() - last_tap > 8:
        last_tap = time.monotonic()
        run([str(ADB), "shell", "input tap 150 300"])


def on_tablet_connected():
    adb = str(ADB)
    run([adb, "reverse", f"tcp:{PORT}", f"tcp:{PORT}"])
    run([adb, "reverse", "tcp:8766", "tcp:8766"])        # second-screen video + touch
    run([adb, "reverse", "tcp:8767", "tcp:8767"])        # laptop sound -> tablet speakers
    try:                                                  # this tablet's screen, landscape (second-screen size)
        w, h = map(int, run([adb, "shell", "wm size"]).strip().split(":")[-1].split("x"))
        state["tablet_size"] = (max(w, h), min(w, h))
    except ValueError:
        pass
    run([adb, "shell", "settings put system accelerometer_rotation 0; settings put system user_rotation 1; "
                       "svc power stayon usb; input keyevent KEYCODE_WAKEUP"])
    if "dev.somesh.commandcenter" in run([adb, "shell", "pm list packages dev.somesh.commandcenter"]):
        # our tablet app: full screen by design, no Chrome / tap workarounds needed
        run([adb, "shell", "am start -n dev.somesh.commandcenter/.MainActivity"])
    else:
        if not tidy_chrome_tabs():
            run([adb, "shell", f"am start -a android.intent.action.VIEW -d http://localhost:{PORT}/ "
                               "-e com.android.browser.application_id commandcenter com.android.chrome"])
        time.sleep(4)
        tap_for_fullscreen()
    apply_brightness()
    if settings.get("mic_on"):
        mic(True, "tablet connected")


def tablet_watch():
    """Blocks on adb's track-devices socket; costs nothing while idle."""
    online = False
    while True:
        try:
            s = socket.create_connection(("127.0.0.1", 5037), timeout=5)
            s.settimeout(None)
            req = b"host:track-devices"
            s.sendall(b"%04x" % len(req) + req)
            if _recvn(s, 4) != b"OKAY":
                raise ConnectionError
            while True:
                data = _recvn(s, int(_recvn(s, 4), 16)).decode()
                now = any(l.split("\t")[-1] == "device" for l in data.splitlines())
                if now != online:
                    online = now
                    state["tablet"] = online
                    broadcast("tablet", online)
                    if online:
                        threading.Thread(target=on_tablet_connected, daemon=True).start()
        except (OSError, ConnectionError, ValueError):
            run([str(ADB), "start-server"], timeout=20)
            time.sleep(3)


# ------------------------------------------------------------------ microphone (scrcpy)
mic_proc = None


def mic_log(msg):
    """Tiny rolling log so mic on/off changes can be traced (kept under ~20 KB)."""
    f = ROOT / "mic.log"
    try:
        old = f.read_text(encoding="utf-8")[-15000:] if f.exists() else ""
        f.write_text(old + time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n", encoding="utf-8")
    except OSError:
        pass


def _mic_watch(proc):
    """If scrcpy stops on its own, retry while the mic is meant to be on (tablet still waking up,
    adb just restarted...). Gives up after 3 quick failures and shows the mic as off."""
    started = time.monotonic()
    proc.wait()
    if proc is not mic_proc:
        return
    mic_log(f"scrcpy exited code={proc.returncode} after {time.monotonic() - started:.0f}s")
    if settings.get("mic_on") and state["tablet"]:
        _mic_watch.fails = getattr(_mic_watch, "fails", 0) + 1 if time.monotonic() - started < 20 else 1
        if _mic_watch.fails <= 3:
            time.sleep(3)
            mic_log(f"retry {_mic_watch.fails}")
            mic(True, "retry")
            return
    state["mic"] = {"on": False, "available": SCRCPY.exists()}
    broadcast("mic", state["mic"])


def _mic_route(pid):
    """Pin scrcpy's output to CABLE Input so the mic never plays out of the speakers."""
    time.sleep(2)   # scrcpy needs an audio session before Windows accepts the route
    run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(ROOT / "mic-route.ps1"), "-ProcessId", str(pid)], timeout=30)


def mic(on, why="request"):
    global mic_proc
    mic_log(f"mic {'ON' if on else 'OFF'} ({why})")
    if mic_proc and mic_proc.poll() is None:
        old, mic_proc = mic_proc, None
        old.terminate()
    if on and SCRCPY.exists() and state["tablet"]:
        # raw PCM over USB: no encoding on the tab, no decoding on the laptop
        mic_proc = subprocess.Popen(
            # default source is Android's call mode: auto-gain + noise suppression, ~4-10x louder
            [str(SCRCPY), "--no-video", "--no-window", "--no-control", f"--audio-source={settings['mic_source']}",
             "--audio-codec=raw", "--require-audio", "--audio-buffer=40"],
            creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, "ADB": str(ADB)})
        threading.Thread(target=_mic_watch, args=(mic_proc,), daemon=True).start()
        threading.Thread(target=_mic_route, args=(mic_proc.pid,), daemon=True).start()
    state["mic"] = {"on": bool(on), "available": SCRCPY.exists()}
    broadcast("mic", state["mic"])
    if settings.get("mic_on") != bool(on):
        settings["mic_on"] = bool(on)
        SETTINGS_FILE.write_text(json.dumps(settings, indent=1), encoding="utf-8")
    return True


# ------------------------------------------------------------------ apps
def app_key(appid):
    return hashlib.sha1(appid.encode()).hexdigest()


def load_apps():
    try:
        return json.loads(APPS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_apps(apps):
    APPS_FILE.write_text(json.dumps(apps, indent=1), encoding="utf-8")


def start_apps():
    out = run(["powershell", "-NoProfile", "-Command",
               "Get-StartApps | Where-Object { $_.AppID -notmatch '^https?:' } | "
               "Select-Object Name,AppID | ConvertTo-Json -Compress"], timeout=30)
    try:
        items = json.loads(out or "[]")
    except json.JSONDecodeError:
        return []
    seen, res = set(), []
    for it in sorted(items, key=lambda x: x["Name"].lower()):
        n = it["Name"]
        if n.lower() in seen or any(w in n.lower() for w in ("uninstall", "readme", "help", "documentation")):
            continue
        seen.add(n.lower())
        res.append({"name": n, "appid": it["AppID"]})
    return res


def extract_icons(appids):
    need = [a for a in appids if not (ICONS / f"{app_key(a)}.png").exists()]
    if need:
        run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "icons.ps1"),
             "-Out", str(ICONS), "-Ids", "|".join(need)], timeout=60)


def akey(a):
    return app_key(a.get("appid") or a["url"])


def public_apps(apps):
    out = []
    for a in apps:
        k = akey(a)
        icon = next((f"{k}{ext}" for ext in (".png", ".svg") if (ICONS / f"{k}{ext}").exists()), None)
        out.append({"id": k, "name": a["name"], "icon": icon, "web": "url" in a})
    return out


def apps_changed(apps):
    """Save and push the new home screen to every open view (tablet + settings app)."""
    save_apps(apps)
    pub = public_apps(apps)
    broadcast("apps", pub)
    return pub


def fetch_web_icon(url):
    """Grab the site's best icon once (manifest > apple-touch > fluid > favicon) and cache it."""
    import re
    import urllib.request
    from urllib.parse import urljoin

    def get(u, limit=2_000_000):
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 CommandCenter"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.read(limit), r.headers.get_content_type()

    try:
        html = get(url, 400_000)[0].decode("utf-8", "replace")
    except Exception:
        return
    cands = []  # (score, url)
    for tag in re.findall(r"<link\b[^>]*>", html, re.I):
        rel = (re.search(r'rel=["\']([^"\']+)', tag, re.I) or [None, ""])[1].lower()
        href = (re.search(r'href=["\']([^"\']+)', tag, re.I) or [None, ""])[1]
        if not href:
            continue
        if rel == "manifest":
            try:
                man = json.loads(get(urljoin(url, href))[0])
                for ic in man.get("icons", []):
                    size = max((int(s.split("x")[0]) for s in ic.get("sizes", "0x0").split() if "x" in s), default=0)
                    if ic.get("src", "").endswith(".png") or "png" in ic.get("type", ""):
                        cands.append((1000 + size, urljoin(urljoin(url, href), ic["src"])))
            except Exception:
                pass
        elif "apple-touch-icon" in rel:
            cands.append((900, urljoin(url, href)))
        elif rel == "fluid-icon":
            cands.append((850, urljoin(url, href)))
        elif "icon" in rel and "mask" not in rel:
            cands.append((500 if href.endswith(".svg") else 100, urljoin(url, href)))
    cands.append((10, urljoin(url, "/favicon.ico")))
    k = app_key(url)
    for _, u in sorted(cands, reverse=True):
        try:
            data, ctype = get(u)
        except Exception:
            continue
        ext = ".svg" if "svg" in ctype or u.endswith(".svg") else ".png"
        if ext == ".png" and not data.startswith(b"\x89PNG"):
            continue   # skip .ico and other formats the tablet can't show nicely
        (ICONS / f"{k}{ext}").write_bytes(data)
        return


def ensure_default_apps():
    apps = load_apps()
    if apps is None:
        avail = {a["name"]: a for a in start_apps()}
        apps = [avail[n] for n in DEFAULT_APPS if n in avail]
        extract_icons([a["appid"] for a in apps])
        save_apps(apps)
    return apps


# ------------------------------------------------------------------ actions
VK = {"play": 0xB3, "next": 0xB0, "prev": 0xB1, "vol_up": 0xAF, "vol_down": 0xAE, "mute": 0xAD}


def press(*keys):
    u = ctypes.windll.user32
    for k in keys:
        u.keybd_event(k, 0, 0, 0)
    for k in reversed(keys):
        u.keybd_event(k, 0, 2, 0)


def do_action(name):
    if name in ("play", "next", "prev") and NOW_PLAYING and NOW_PLAYING.control(name):
        return True                       # controlled the playing app directly
    if name in VK:
        press(VK[name])
    elif name == "lock":
        ctypes.windll.user32.LockWorkStation()
    elif name == "snip":
        press(0x5B, 0x10, 0x53)
    elif name == "taskmgr":
        press(0x11, 0x10, 0x1B)
    elif name == "desktop":
        press(0x5B, 0x44)
    elif name == "discord_mute":      # Discord › Settings › Keybinds: Toggle Mute = Ctrl+Shift+Alt+M
        press(0x11, 0x10, 0x12, 0x4D)
    elif name == "discord_deafen":    # Toggle Deafen = Ctrl+Shift+Alt+D
        press(0x11, 0x10, 0x12, 0x44)
    elif name == "screenshot":
        press(0x5B, 0x2C)  # Win+PrtSc: full screenshot saved to Pictures\Screenshots
    elif name == "monitor_off":
        ctypes.windll.user32.PostMessageW(0xFFFF, 0x0112, 0xF170, 2)  # turn laptop display off
    elif name == "explorer":
        subprocess.Popen(["explorer.exe"], creationflags=NO_WINDOW)
    elif name == "calc":
        subprocess.Popen(["calc.exe"], creationflags=NO_WINDOW)
    elif name == "emoji":
        press(0x5B, 0xBE)  # Win+. emoji panel
    elif name == "clipboard":
        press(0x5B, 0x56)  # Win+V clipboard history
    else:
        return False
    return True


claude_asks = {}   # id -> {"info": {...}, "event": threading.Event(), "decision": None}


def claude_ask(info):
    aid = str(time.time_ns())
    claude_asks[aid] = {"info": {**info, "id": aid, "time": time.time()}, "event": threading.Event(), "decision": None}
    broadcast("claude_ask", claude_asks[aid]["info"])
    return aid


def claude_wait(aid, wait):
    a = claude_asks.get(aid)
    if not a:
        return None
    a["event"].wait(min(float(wait), 120))
    claude_asks.pop(aid, None)
    broadcast("claude_ask_done", {"id": aid, "decision": a["decision"]})   # removes the card everywhere
    return a["decision"]


def claude_answer(aid, decision):
    a = claude_asks.get(aid)
    if a and decision in ("allow", "deny"):
        a["decision"] = decision
        a["event"].set()
        return True
    return False


def add_note(title, body="", level="info"):
    note = {"id": str(time.time_ns()), "title": str(title)[:120], "body": str(body)[:400],
            "level": level, "time": time.time()}
    with lock:
        state["notes"] = ([note] + state["notes"])[:30]
    broadcast("note", note)


# ------------------------------------------------------------------ http
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css",
         ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send(self, code, body=b"", ctype="application/json", cache=False):
        if not isinstance(body, bytes):
            body = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "max-age=31536000" if cache else "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/events":
            return self.stream()
        if path == "/apps":
            return self.send(200, public_apps(load_apps() or []))
        if path == "/settings":
            return self.send(200, settings)
        if path.startswith("/media/art"):
            art = NOW_PLAYING.art[1] if NOW_PLAYING else b""
            ctype = "image/png" if art[:4] == b"\x89PNG" else "image/jpeg"
            return self.send(200 if art else 404, art, ctype, cache=True)
        if path == "/claude/answer":       # long-poll from the PermissionRequest hook
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            return self.send(200, {"decision": claude_wait(q.get("id", [""])[0], q.get("wait", ["45"])[0])})
        if path == "/status":
            me = psutil.Process()
            return self.send(200, {"ram_mb": round(me.memory_info().rss / 2**20, 1),
                                   "cpu": me.cpu_percent(interval=0.5), "tablet": state["tablet"],
                                   "mic": state["mic"], "autostart": STARTUP_LNK.exists(),
                                   "viewers": len(subscribers),
                                   "display": {"active": bool(DISPLAY and DISPLAY.active),
                                               "latency_ms": DISPLAY and DISPLAY.latency_ms,
                                               "driver": display_driver_installed()},
                                   "speaker": {"active": bool(SPEAKER and SPEAKER.active)},
                                   "claude_asks": list(claude_asks)})
        if path == "/startapps":
            mine = {a.get("appid") for a in load_apps() or []}
            return self.send(200, [{"name": a["name"], "appid": a["appid"]}
                                   for a in start_apps() if a["appid"] not in mine])
        if path.startswith("/icons/"):
            f = ICONS / Path(path).name
            if f.is_file():
                return self.send(200, f.read_bytes(), TYPES.get(f.suffix, "image/png"), cache=True)
            return self.send(404, b"")
        f = (WEB / (path.lstrip("/") or "index.html")).resolve()
        if WEB in f.parents and f.is_file():
            return self.send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))
        self.send(404, b"not found", "text/plain")

    def do_POST(self):
        d = self.json_body()
        p = self.path
        if p == "/action":
            ok = do_action(d.get("name"))
            return self.send(200 if ok else 400, {"ok": ok})
        if p == "/launch":
            for a in load_apps() or []:
                if akey(a) == d.get("id"):
                    if "url" in a:
                        os.startfile(a["url"])       # opens in the default browser
                    else:
                        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{a['appid']}"],
                                         creationflags=NO_WINDOW)
                    return self.send(200, {"ok": True})
            return self.send(404, {"ok": False})
        if p == "/apps/add":
            apps = load_apps() or []
            if d.get("appid") and all(a.get("appid") != d["appid"] for a in apps):
                extract_icons([d["appid"]])
                apps.append({"name": d.get("name") or d["appid"], "appid": d["appid"]})
                save_apps(apps)
            return self.send(200, apps_changed(apps))
        if p == "/apps/add_web":
            url = (d.get("url") or "").strip()
            if url and "://" not in url:
                url = "https://" + url
            if not url.startswith(("http://", "https://")):
                return self.send(400, {"error": "bad url"})
            apps = load_apps() or []
            if all(a.get("url") != url for a in apps):
                fetch_web_icon(url)
                from urllib.parse import urlparse
                name = (d.get("name") or "").strip() or urlparse(url).netloc.replace("www.", "")
                apps.append({"name": name, "url": url})
                save_apps(apps)
            return self.send(200, apps_changed(apps))
        if p == "/apps/remove":
            apps = [a for a in load_apps() or [] if akey(a) != d.get("id")]
            save_apps(apps)
            return self.send(200, apps_changed(apps))
        if p == "/apps/order":
            order = d.get("ids") or []
            apps = sorted(load_apps() or [], key=lambda a: order.index(akey(a))
                          if akey(a) in order else 999)
            save_apps(apps)
            return self.send(200, apps_changed(apps))
        if p == "/apps/rename":
            apps = load_apps() or []
            for a in apps:
                if akey(a) == d.get("id") and str(d.get("name", "")).strip():
                    a["name"] = str(d["name"]).strip()[:40]
            save_apps(apps)
            return self.send(200, apps_changed(apps))
        if p == "/settings":
            return self.send(200, update_settings(d))
        if p == "/autostart":
            return self.send(200, {"on": set_autostart(bool(d.get("on")))})
        if p == "/claude/event":  # from claude_hook.py: Claude finished / needs attention
            if d.get("kind") == "notify" and claude_asks:
                return self.send(200, {"ok": True})            # the Allow/Deny card already covers it
            title = f"Claude · {d.get('project', '')}".strip(" ·")
            add_note(title, d.get("body", ""), "claude" if d.get("kind") == "done" else "claude-ask")
            return self.send(200, {"ok": True})
        if p == "/claude/ask":
            return self.send(200, {"id": claude_ask({k: str(d.get(k, ""))[:400] for k in ("project", "tool", "detail")}
                                                    | {"wait": int(d.get("wait", 45))})})
        if p == "/claude/reply":  # the tablet's Allow / Deny tap
            return self.send(200, {"ok": claude_answer(d.get("id"), d.get("decision"))})
        if p == "/media/seek":
            return self.send(200, {"ok": bool(NOW_PLAYING and NOW_PLAYING.control("seek", d.get("pos", 0)))})
        if p == "/volume":
            import audio
            audio.set_volume(d.get("level", 0.5))
            if d.get("level", 0) > 0 and audio.get_volume()[1]:
                audio.set_mute(False)          # dragging the volume up also unmutes
            return self.send(200, {"ok": True})
        if p == "/mode":          # switch the tablet between "dashboard" and "display"
            mode = "display" if d.get("mode") == "display" else "dashboard"
            broadcast("mode", mode)
            return self.send(200, {"mode": mode})
        if p == "/display_state":  # the tablet app reports entering / leaving second-screen mode
            state["display"] = bool(d.get("on"))
            broadcast("display", state["display"])
            return self.send(200, {"ok": True})
        if p == "/need_tap":   # the tablet page reports it isn't full screen yet
            if state["tablet"]:
                threading.Thread(target=tap_for_fullscreen, daemon=True).start()
            return self.send(200, {"ok": True})
        if p == "/test_note":
            add_note("Test notification", "This is how alerts look and sound on the tab.", "info")
            return self.send(200, {"ok": True})
        if p == "/mic":
            who = self.headers.get("Referer") or self.headers.get("User-Agent", "?")
            return self.send(200, {"ok": mic(bool(d.get("on")), f"button: {who[:80]}")})
        if p == "/notify":
            add_note(d.get("title") or "Notification", d.get("body", ""), d.get("level", "info"))
            return self.send(200, {"ok": True})
        self.send(404, {})

    def stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        q: queue.Queue = queue.Queue(maxsize=30)
        web_version = int(max(f.stat().st_mtime for f in WEB.iterdir() if f.is_file()))
        hello = {"tablet": state["tablet"], "mic": state["mic"], "notes": state["notes"], "settings": settings,
                 "version": web_version,   # the tablet reloads itself when the dashboard files changed
                 "asks": [a["info"] for a in claude_asks.values()],
                 "np": NOW_PLAYING.state if NOW_PLAYING else None, "discord": state.get("discord", False)}
        try:
            self.wfile.write(f"event: hello\ndata: {json.dumps(hello)}\n\n".encode())
            self.wfile.flush()
            subscribers.append(q)
            while True:
                try:
                    msg = q.get(timeout=20)
                except queue.Empty:
                    msg = b": ping\n\n"
                self.wfile.write(msg)
                self.wfile.flush()
        except OSError:
            pass
        finally:
            if q in subscribers:
                subscribers.remove(q)


if __name__ == "__main__":
    threading.Thread(target=ensure_default_apps, daemon=True).start()
    threading.Thread(target=stats_loop, daemon=True).start()
    threading.Thread(target=tablet_watch, daemon=True).start()
    threading.Thread(target=discord_watch, daemon=True).start()

    def _display_changed(on):
        state["display"] = on
        broadcast("display", on)

    import display   # second-screen mode; idle (one blocked socket) until the tablet asks for it
    DISPLAY = display.Display(_display_changed, lambda: settings.get("display_mirror", False),
                              lambda: state.get("tablet_size", (1280, 800)))
    threading.Thread(target=DISPLAY.serve, daemon=True).start()

    try:
        import media     # Now Playing; polls once a second only while the dashboard is open
        NOW_PLAYING = media.NowPlaying(lambda s: broadcast("np", s), lambda: bool(subscribers))
    except Exception as e:  # noqa: BLE001 - the dashboard works without it
        NOW_PLAYING = None

    import audio     # tablet-speaker mode; numpy/soundcard only load once it's switched on
    SPEAKER = audio.TabSpeaker(lambda: settings.get("tab_speaker", False),
                               lambda: settings.get("speaker_mute_laptop", True))
    threading.Thread(target=SPEAKER.serve, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
