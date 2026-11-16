"""Tablet as trackpad / keyboard / gamepad: turns small JSON events from the tablet into real Windows input.

Events (POST /input, a list):
  {"t":"m","x":dx,"y":dy}            relative mouse move
  {"t":"b","b":"l|r|m","d":1|0}      mouse button down / up
  {"t":"w","y":n,"x":n}              scroll (wheel notches * 120), x = horizontal
  {"t":"k","k":"KeyName","d":1|0}    key down / up (names below)
  {"t":"txt","s":"hello"}            type text (any language, emoji)
  {"t":"pad","b":[...],"lx":-1..1,"ly":-1..1}   gamepad state (mapped to keys, or a virtual Xbox pad if available)
"""
import ctypes
from ctypes import wintypes as w

u32 = ctypes.WinDLL("user32", use_last_error=True)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD), ("dwFlags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD), ("time", w.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", w.DWORD), ("u", _U)]


u32.SendInput.argtypes = [w.UINT, ctypes.POINTER(INPUT), ctypes.c_int]

M_MOVE, M_WHEEL, M_HWHEEL = 0x1, 0x800, 0x1000
BTN = {"l": (0x2, 0x4), "r": (0x8, 0x10), "m": (0x20, 0x40)}
K_EXT, K_UP, K_UNICODE, K_SCAN = 0x1, 0x2, 0x4, 0x8

# key names (as the tablet sends them) -> Windows virtual-key codes
VK = {"Esc": 0x1B, "Tab": 0x09, "Caps": 0x14, "Shift": 0xA0, "Ctrl": 0xA2, "Alt": 0xA4, "Win": 0x5B,
      "Space": 0x20, "Enter": 0x0D, "Backspace": 0x08, "Delete": 0x2E, "Insert": 0x2D,
      "Home": 0x24, "End": 0x23, "PgUp": 0x21, "PgDn": 0x22,
      "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28, "PrtSc": 0x2C, "Menu": 0x5D,
      "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA, "'": 0xDE,
      ",": 0xBC, ".": 0xBE, "/": 0xBF}
VK.update({f"F{i}": 0x6F + i for i in range(1, 13)})
VK.update({c: ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"})
EXTENDED = {0x2E, 0x2D, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0x5B, 0x5D, 0x2C}


def _send(*items):
    arr = (INPUT * len(items))(*items)
    u32.SendInput(len(items), arr, ctypes.sizeof(INPUT))


def _mouse(flags, dx=0, dy=0, data=0):
    i = INPUT(type=0)
    i.u.mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)
    return i


def _key(vk, down):
    """Scan-code based, so games (DirectInput/raw input) see it too."""
    scan = u32.MapVirtualKeyW(vk, 0)
    flags = K_SCAN | (0 if down else K_UP) | (K_EXT if vk in EXTENDED else 0)
    i = INPUT(type=1)
    i.u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return i


def key(name, down):
    vk = VK.get(name) or VK.get(str(name).upper())
    if vk:
        _send(_key(vk, down))


def text(s):
    """Types any text (emoji / other languages included) as UTF-16 units, so the keyboard layout doesn't matter."""
    items = []
    data = str(s)[:2000].encode("utf-16-le")
    for pos in range(0, len(data), 2):
        unit = int.from_bytes(data[pos:pos + 2], "little")
        for down in (True, False):
            i = INPUT(type=1)
            i.u.ki = KEYBDINPUT(0, unit, K_UNICODE | (0 if down else K_UP), 0, 0)
            items.append(i)
    if items:
        _send(*items)


# ------------------------------------------------------------------ gamepad
# Default: keyboard mapping (works in most PC games, no driver). Real Xbox pad if `vgamepad` + ViGEmBus exist.
PAD_KEYS = {"a": "Space", "b": "Ctrl", "x": "E", "y": "Q", "lb": "1", "rb": "2", "lt": "R", "rt": "F",
            "start": "Esc", "back": "Tab", "up": "Up", "down": "Down", "left": "Left", "right": "Right",
            "ls": "Shift", "rs": "V"}
STICK = {"l": "A", "r": "D", "u": "W", "d": "S"}


class Gamepad:
    def __init__(self):
        self.held = set()
        self.xbox = None
        try:                                    # optional virtual Xbox 360 controller
            import vgamepad
            self.vg = vgamepad
            self.xbox = vgamepad.VX360Gamepad()
        except Exception:  # noqa: BLE001 - driver not installed: keyboard mapping
            self.xbox = None

    @property
    def mode(self):
        return "xbox" if self.xbox else "keyboard"

    def update(self, buttons, lx, ly):
        if self.xbox:
            return self._xbox(buttons, lx, ly)
        want = {PAD_KEYS[b] for b in buttons if b in PAD_KEYS}
        t = 0.38                                 # stick dead-zone -> WASD
        if lx < -t: want.add(STICK["l"])
        if lx > t: want.add(STICK["r"])
        if ly < -t: want.add(STICK["u"])
        if ly > t: want.add(STICK["d"])
        for k in self.held - want:
            key(k, False)
        for k in want - self.held:
            key(k, True)
        self.held = want

    def _xbox(self, buttons, lx, ly):
        B = self.vg.XUSB_BUTTON
        names = {"a": B.XUSB_GAMEPAD_A, "b": B.XUSB_GAMEPAD_B, "x": B.XUSB_GAMEPAD_X, "y": B.XUSB_GAMEPAD_Y,
                 "lb": B.XUSB_GAMEPAD_LEFT_SHOULDER, "rb": B.XUSB_GAMEPAD_RIGHT_SHOULDER,
                 "start": B.XUSB_GAMEPAD_START, "back": B.XUSB_GAMEPAD_BACK,
                 "up": B.XUSB_GAMEPAD_DPAD_UP, "down": B.XUSB_GAMEPAD_DPAD_DOWN,
                 "left": B.XUSB_GAMEPAD_DPAD_LEFT, "right": B.XUSB_GAMEPAD_DPAD_RIGHT,
                 "ls": B.XUSB_GAMEPAD_LEFT_THUMB, "rs": B.XUSB_GAMEPAD_RIGHT_THUMB}
        self.xbox.reset()
        for b in buttons:
            if b in names:
                self.xbox.press_button(button=names[b])
        self.xbox.left_trigger_float(1.0 if "lt" in buttons else 0.0)
        self.xbox.right_trigger_float(1.0 if "rt" in buttons else 0.0)
        self.xbox.left_joystick_float(max(-1, min(1, lx)), max(-1, min(1, -ly)))
        self.xbox.update()

    def release(self):
        self.update([], 0, 0)


PAD = None


def handle(events):
    global PAD
    moves = None
    for e in events if isinstance(events, list) else [events]:
        t = e.get("t")
        if t == "m":
            dx, dy = int(e.get("x", 0)), int(e.get("y", 0))
            if dx or dy:
                moves = (moves[0] + dx, moves[1] + dy) if moves else (dx, dy)
                continue
        if moves:                                # flush accumulated movement first, in order
            _send(_mouse(M_MOVE, *moves))
            moves = None
        if t == "b" and e.get("b") in BTN:
            _send(_mouse(BTN[e["b"]][0 if e.get("d") else 1]))
        elif t == "w":
            if e.get("y"):
                _send(_mouse(M_WHEEL, data=int(-e["y"] * 120)))
            if e.get("x"):
                _send(_mouse(M_HWHEEL, data=int(e["x"] * 120)))
        elif t == "k":
            key(e.get("k"), bool(e.get("d")))
        elif t == "txt":
            text(e.get("s", ""))
        elif t == "pad":
            if PAD is None:
                PAD = Gamepad()
            PAD.update(e.get("b") or [], float(e.get("lx", 0)), float(e.get("ly", 0)))
    if moves:
        _send(_mouse(M_MOVE, *moves))
    return {"ok": True, "pad": PAD.mode if PAD else None}
