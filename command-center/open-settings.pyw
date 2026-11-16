"""Opens the Command Center settings app (starts the server first if it isn't running).

Uses Edge's chromeless --app window with its own small profile, so it looks like a normal
desktop app and frees all of its memory when you close it.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
URL = "http://localhost:8765/settings.html"
NO_WINDOW = 0x08000000


def server_up():
    try:
        socket.create_connection(("127.0.0.1", 8765), timeout=0.3).close()
        return True
    except OSError:
        return False


if not server_up():
    pyw = Path(sys.executable).with_name("pythonw.exe")
    subprocess.Popen([str(pyw if pyw.exists() else sys.executable), str(ROOT / "server.py")],
                     cwd=ROOT, creationflags=NO_WINDOW)
    for _ in range(40):
        if server_up():
            break
        time.sleep(0.25)

PF, PF86, LAD = (os.environ.get(k, "") for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"))
# Brave/Chrome first: they never sign the app window into an account. Edge is the fallback.
CANDIDATES = [Path(PF) / r"BraveSoftware\Brave-Browser\Application\brave.exe",
              Path(LAD) / r"BraveSoftware\Brave-Browser\Application\brave.exe",
              Path(PF) / r"Google\Chrome\Application\chrome.exe",
              Path(PF86) / r"Microsoft\Edge\Application\msedge.exe"]
browser = next((p for p in CANDIDATES if p.exists()), None)
profile = Path(LAD) / "CommandCenter" / "settings-window"   # private, signed-out, no sync
if browser and browser.name == "brave.exe":
    # private window profile: usage analytics off, notice already answered (most private choice)
    import json
    state_file = profile / "Local State"
    try:
        st = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    st.setdefault("brave", {})["p3a"] = {"enabled": False, "notice_acknowledged": True}
    st["brave"]["stats"] = {"reporting_enabled": False}
    st.setdefault("user_experience_metrics", {})["reporting_enabled"] = False
    profile.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(st), encoding="utf-8")
APP_ID = "SomeshThakur.CommandCenter"
ICON = ROOT / "command-center.ico"


def brand_window(timeout=12.0):
    """Give the app window its own taskbar identity: our name, icon, and relaunch command.
    Without this Windows groups it with Brave and pins plain Brave."""
    import ctypes
    from ctypes import wintypes as w, byref, POINTER, c_void_p, c_ulong, c_ushort, Structure, WINFUNCTYPE

    class GUID(Structure):
        _fields_ = [("a", c_ulong), ("b", c_ushort), ("c", c_ushort), ("d", ctypes.c_ubyte * 8)]

    class PKEY(Structure):
        _fields_ = [("fmtid", GUID), ("pid", c_ulong)]

    class PROPVARIANT(Structure):
        _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort),
                    ("p", c_void_p), ("p2", c_void_p)]

    def guid(s):
        g = GUID()
        ctypes.oledll.ole32.CLSIDFromString(s, byref(g))
        return g

    user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
    user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    shell32.SHGetPropertyStoreForWindow.argtypes = [w.HWND, POINTER(GUID), POINTER(c_void_p)]
    ctypes.windll.ole32.CoInitialize(None)

    def find():
        found = []

        @WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        def cb(hwnd, _):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value in ("TabDeck", "Command Center") and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True
        user32.EnumWindows(cb, 0)
        return found

    deadline = time.time() + timeout
    hwnds = []
    while time.time() < deadline and not hwnds:
        time.sleep(0.25)
        hwnds = find()
    fmt = guid("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}")      # System.AppUserModel.*
    pyw = Path(sys.executable).with_name("pythonw.exe")
    props = [(2, f'"{pyw}" "{ROOT / "open-settings.pyw"}"'),  # RelaunchCommand
             (4, "TabDeck"),                                   # RelaunchDisplayNameResource
             (3, f"{ICON},0"),                                 # RelaunchIconResource
             (5, APP_ID)]                                      # ID (set last)
    for hwnd in hwnds:
        store = c_void_p()
        if shell32.SHGetPropertyStoreForWindow(hwnd, byref(guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")),
                                               byref(store)) != 0:
            continue
        vt = ctypes.cast(store, POINTER(POINTER(c_void_p)))[0]
        set_value = WINFUNCTYPE(ctypes.HRESULT, c_void_p, POINTER(PKEY), POINTER(PROPVARIANT))(vt[6])
        commit = WINFUNCTYPE(ctypes.HRESULT, c_void_p)(vt[7])
        release = WINFUNCTYPE(c_ulong, c_void_p)(vt[2])
        keep = []
        for pid, val in props:
            s = ctypes.create_unicode_buffer(val)
            keep.append(s)
            pv = PROPVARIANT(vt=31)                            # VT_LPWSTR
            pv.p = ctypes.cast(s, c_void_p)
            set_value(store, byref(PKEY(fmt, pid)), byref(pv))
        commit(store)
        release(store)
    return len(hwnds)


if browser:
    subprocess.Popen([str(browser), f"--app={URL}", f"--user-data-dir={profile}", "--window-size=1280,820",
                      "--no-first-run", "--no-default-browser-check", "--disable-sync", "--disable-extensions",
                      "--disable-background-networking", "--disable-component-update", "--disable-default-apps",
                      "--renderer-process-limit=2",
                      "--disable-features=msImplicitSignin,msEdgeSidebar,Translate,OptimizationHints,MediaRouter"],
                     creationflags=NO_WINDOW)
    brand_window()
else:
    os.startfile(URL)
