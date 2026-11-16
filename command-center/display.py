"""Second-screen mode: the tablet becomes a real extended Windows display with touch.

Pipeline (all of it only runs while the tablet is in second-screen mode):
  Parsec virtual display (added on demand) -> ffmpeg ddagrab (GPU capture, zero-copy)
  -> h264_nvenc ultra-low-latency -> framed over USB (adb reverse tcp:8766)
  -> tablet app hardware-decodes onto the screen; touches come back as Windows touch input.
"""
import ctypes
import os
import socket
import struct
import subprocess
import threading
import time
from ctypes import wintypes as w, byref, sizeof, Structure, POINTER, c_void_p, c_ulong, c_ushort, c_ubyte

PORT = 8766
NO_WINDOW = 0x08000000
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)
setupapi = ctypes.WinDLL("setupapi", use_last_error=True)


def log(msg):
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "display.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    except OSError:
        pass


# ======================================================================= Parsec virtual display
class GUID(Structure):
    _fields_ = [("a", c_ulong), ("b", c_ushort), ("c", c_ushort), ("d", c_ubyte * 8)]


VDD_GUID = GUID(0x00b41627, 0x04c4, 0x429e, (c_ubyte * 8)(0xa2, 0x6e, 0x02, 0x65, 0xcf, 0x50, 0xc8, 0xfa))
IOCTL_ADD, IOCTL_REMOVE, IOCTL_UPDATE, IOCTL_VERSION = 0x0022e004, 0x0022a008, 0x0022a00c, 0x0022e010


class SP_DEVICE_INTERFACE_DATA(Structure):
    _fields_ = [("cbSize", w.DWORD), ("guid", GUID), ("flags", w.DWORD), ("reserved", ctypes.c_size_t)]


class OVERLAPPED(Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                ("Offset", w.DWORD), ("OffsetHigh", w.DWORD), ("hEvent", w.HANDLE)]


setupapi.SetupDiGetClassDevsW.restype = w.HANDLE
setupapi.SetupDiGetClassDevsW.argtypes = [POINTER(GUID), w.LPCWSTR, w.HWND, w.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [w.HANDLE, c_void_p, POINTER(GUID), w.DWORD, POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [w.HANDLE, POINTER(SP_DEVICE_INTERFACE_DATA), c_void_p, w.DWORD, POINTER(w.DWORD), c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [w.HANDLE]
k32.CreateFileW.restype = w.HANDLE
k32.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c_void_p, w.DWORD, w.DWORD, w.HANDLE]
k32.DeviceIoControl.argtypes = [w.HANDLE, w.DWORD, c_void_p, w.DWORD, c_void_p, w.DWORD, POINTER(w.DWORD), POINTER(OVERLAPPED)]
k32.GetOverlappedResultEx.argtypes = [w.HANDLE, POINTER(OVERLAPPED), POINTER(w.DWORD), w.DWORD, w.BOOL]
k32.CreateEventW.restype = w.HANDLE
k32.CloseHandle.argtypes = [w.HANDLE]


class ParsecVDD:
    def __init__(self):
        self.h = None
        self.index = None
        self._stop = threading.Event()

    @staticmethod
    def installed():
        return ParsecVDD._path() is not None

    @staticmethod
    def _path():
        hdev = setupapi.SetupDiGetClassDevsW(byref(VDD_GUID), None, None, 0x12)  # PRESENT | DEVICEINTERFACE
        if hdev in (None, w.HANDLE(-1).value):
            return None
        try:
            ifd = SP_DEVICE_INTERFACE_DATA()
            ifd.cbSize = sizeof(ifd)
            if not setupapi.SetupDiEnumDeviceInterfaces(hdev, None, byref(VDD_GUID), 0, byref(ifd)):
                return None
            need = w.DWORD()
            setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, byref(ifd), None, 0, byref(need), None)
            buf = ctypes.create_string_buffer(need.value)
            ctypes.cast(buf, POINTER(w.DWORD))[0] = 8   # cbSize of SP_DEVICE_INTERFACE_DETAIL_DATA_W on x64
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, byref(ifd), buf, need, None, None):
                return None
            return ctypes.wstring_at(ctypes.addressof(buf) + 4)
        finally:
            setupapi.SetupDiDestroyDeviceInfoList(hdev)

    def _ioctl(self, code, data=b""):
        inbuf = ctypes.create_string_buffer(32)
        inbuf[:len(data)] = data
        out = w.DWORD(0)
        ov = OVERLAPPED()
        ov.hEvent = k32.CreateEventW(None, True, False, None)
        try:
            got = w.DWORD()
            k32.DeviceIoControl(self.h, code, inbuf, 32, byref(out), 4, None, byref(ov))
            if not k32.GetOverlappedResultEx(self.h, byref(ov), byref(got), 5000, False):
                raise OSError(ctypes.get_last_error(), "Parsec VDD ioctl failed")
            return out.value
        finally:
            k32.CloseHandle(ov.hEvent)

    def open(self):
        path = self._path()
        if not path:
            raise RuntimeError("Parsec virtual display driver is not installed")
        h = k32.CreateFileW(path, 0xC0000000, 0x3, None, 3, 0x80 | 0x20000000 | 0x40000000 | 0x80000000, None)
        if h in (None, w.HANDLE(-1).value):
            raise OSError(ctypes.get_last_error(), "cannot open Parsec VDD")
        self.h = h

    def add(self):
        self.index = self._ioctl(IOCTL_ADD)
        self._ioctl(IOCTL_UPDATE)
        self._stop.clear()
        threading.Thread(target=self._keepalive, daemon=True).start()   # driver drops displays without pings
        return self.index

    def _keepalive(self):
        while not self._stop.wait(0.1):
            try:
                self._ioctl(IOCTL_UPDATE)
            except OSError:
                break

    def remove(self):
        self._stop.set()
        if self.h and self.index is not None:
            try:
                i = self.index
                self._ioctl(IOCTL_REMOVE, struct.pack(">H", i & 0xFFFF))   # driver expects big-endian index
                self._ioctl(IOCTL_UPDATE)
            except OSError:
                pass
        self.index = None
        if self.h:
            k32.CloseHandle(self.h)
            self.h = None


# ======================================================================= monitors
class DISPLAY_DEVICEW(Structure):
    _fields_ = [("cb", w.DWORD), ("DeviceName", w.WCHAR * 32), ("DeviceString", w.WCHAR * 128),
                ("StateFlags", w.DWORD), ("DeviceID", w.WCHAR * 128), ("DeviceKey", w.WCHAR * 128)]


class DEVMODEW(Structure):
    _fields_ = [("dmDeviceName", w.WCHAR * 32), ("dmSpecVersion", w.WORD), ("dmDriverVersion", w.WORD),
                ("dmSize", w.WORD), ("dmDriverExtra", w.WORD), ("dmFields", w.DWORD),
                ("dmPositionX", w.LONG), ("dmPositionY", w.LONG), ("dmDisplayOrientation", w.DWORD),
                ("dmDisplayFixedOutput", w.DWORD), ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short),
                ("dmFormName", w.WCHAR * 32), ("dmLogPixels", w.WORD), ("dmBitsPerPel", w.DWORD),
                ("dmPelsWidth", w.DWORD), ("dmPelsHeight", w.DWORD), ("dmDisplayFlags", w.DWORD),
                ("dmDisplayFrequency", w.DWORD), ("dmICMMethod", w.DWORD), ("dmICMIntent", w.DWORD),
                ("dmMediaType", w.DWORD), ("dmDitherType", w.DWORD), ("dmReserved1", w.DWORD),
                ("dmReserved2", w.DWORD), ("dmPanningWidth", w.DWORD), ("dmPanningHeight", w.DWORD)]


def parsec_display():
    """Return (\\\\.\\DISPLAYn, left, top, width, height) of the active Parsec virtual monitor, or None."""
    i = 0
    while True:
        dd = DISPLAY_DEVICEW()
        dd.cb = sizeof(dd)
        if not u32.EnumDisplayDevicesW(None, i, byref(dd), 0):
            return None
        i += 1
        if "parsec" in dd.DeviceString.lower() and dd.StateFlags & 0x1:   # attached to desktop
            dm = DEVMODEW()
            dm.dmSize = sizeof(dm)
            if u32.EnumDisplaySettingsW(dd.DeviceName, -1, byref(dm)):      # ENUM_CURRENT_SETTINGS
                return dd.DeviceName, dm.dmPositionX, dm.dmPositionY, dm.dmPelsWidth, dm.dmPelsHeight


def primary_display():
    """(\\\\.\\DISPLAYn, left, top, width, height) of the main laptop screen (for mirror mode)."""
    i = 0
    while True:
        dd = DISPLAY_DEVICEW()
        dd.cb = sizeof(dd)
        if not u32.EnumDisplayDevicesW(None, i, byref(dd), 0):
            return None
        i += 1
        if dd.StateFlags & 0x4:                                             # PRIMARY_DEVICE
            dm = DEVMODEW()
            dm.dmSize = sizeof(dm)
            if u32.EnumDisplaySettingsW(dd.DeviceName, -1, byref(dm)):
                return dd.DeviceName, dm.dmPositionX, dm.dmPositionY, dm.dmPelsWidth, dm.dmPelsHeight


def set_mode(device, width, height, hz=60):
    """Switch the virtual monitor to the tablet's resolution if the driver offers it."""
    j = 0
    best = None
    while True:
        dm = DEVMODEW()
        dm.dmSize = sizeof(dm)
        if not u32.EnumDisplaySettingsW(device, j, byref(dm)):
            break
        j += 1
        if dm.dmPelsWidth == width and dm.dmPelsHeight == height:
            if best is None or abs(dm.dmDisplayFrequency - hz) < abs(best.dmDisplayFrequency - hz):
                best = dm
    if best is None:
        return False
    best.dmFields = 0x80000 | 0x100000 | 0x400000          # PELSWIDTH | PELSHEIGHT | DISPLAYFREQUENCY
    return u32.ChangeDisplaySettingsExW(device, byref(best), None, 0x1, None) == 0   # CDS_UPDATEREGISTRY


class DXGI_OUTPUT_DESC(Structure):
    _fields_ = [("DeviceName", w.WCHAR * 32), ("DesktopCoordinates", w.RECT), ("AttachedToDesktop", w.BOOL),
                ("Rotation", ctypes.c_int), ("Monitor", w.HANDLE)]


def _com(obj, index, restype, *argtypes):
    vt = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vt[index])


def dxgi_outputs():
    """[(adapter_idx, output_idx, '\\\\.\\DISPLAYn')] exactly as ffmpeg's ddagrab numbers them."""
    dxgi = ctypes.WinDLL("dxgi")
    iid = GUID(0x770aae78, 0xf26f, 0x4dba, (c_ubyte * 8)(0xa8, 0x29, 0x25, 0x3c, 0x83, 0xd1, 0xb3, 0x87))  # IDXGIFactory1
    fac = c_void_p()
    if dxgi.CreateDXGIFactory1(byref(iid), byref(fac)) != 0:
        return []
    res = []
    a = 0
    while True:
        ad = c_void_p()
        if _com(fac, 12, ctypes.c_long, w.UINT, POINTER(c_void_p))(fac, a, byref(ad)) != 0:   # EnumAdapters1
            break
        o = 0
        while True:
            out = c_void_p()
            try:
                hr = _com(ad, 7, ctypes.c_long, w.UINT, POINTER(c_void_p))(ad, o, byref(out))        # EnumOutputs
            except OSError:
                break
            if hr != 0:
                break
            d = DXGI_OUTPUT_DESC()
            _com(out, 7, ctypes.c_long, POINTER(DXGI_OUTPUT_DESC))(out, byref(d))                  # GetDesc
            res.append((a, o, d.DeviceName))
            _com(out, 2, c_ulong)(out)
            o += 1
        _com(ad, 2, c_ulong)(ad)
        a += 1
    _com(fac, 2, c_ulong)(fac)
    return res


# ======================================================================= touch injection
class POINTER_INFO(Structure):
    _fields_ = [("pointerType", w.UINT), ("pointerId", w.UINT), ("frameId", w.UINT), ("pointerFlags", w.UINT),
                ("sourceDevice", w.HANDLE), ("hwndTarget", w.HWND), ("ptPixelLocation", w.POINT),
                ("ptHimetricLocation", w.POINT), ("ptPixelLocationRaw", w.POINT), ("ptHimetricLocationRaw", w.POINT),
                ("dwTime", w.DWORD), ("historyCount", w.UINT), ("InputData", ctypes.c_int32),
                ("dwKeyStates", w.DWORD), ("PerformanceCount", ctypes.c_uint64), ("ButtonChangeType", ctypes.c_int)]


class POINTER_TOUCH_INFO(Structure):
    _fields_ = [("pointerInfo", POINTER_INFO), ("touchFlags", w.UINT), ("touchMask", w.UINT),
                ("rcContact", w.RECT), ("rcContactRaw", w.RECT), ("orientation", w.UINT), ("pressure", w.UINT)]


F_DOWN, F_UPDATE, F_UP = 0x10000 | 0x2 | 0x4, 0x20000 | 0x2 | 0x4, 0x40000


class Touch:
    """Turns tablet touches into real Windows multi-touch on the virtual monitor."""

    def __init__(self):
        self.ok = bool(u32.InitializeTouchInjection(10, 0x1))
        self.rect = (0, 0, 1280, 800)
        self.contacts = {}            # id -> (x, y)
        self.lock = threading.Lock()
        self.last = 0.0
        threading.Thread(target=self._keepalive, daemon=True).start()

    def _inject(self, changed=None, flag=None):
        items = []
        for cid, (x, y) in self.contacts.items():
            f = flag if cid == changed else F_UPDATE
            items.append((cid, x, y, f))
        if changed is not None and changed not in self.contacts and flag == F_UP:
            pass
        if not items:
            return
        arr = (POINTER_TOUCH_INFO * len(items))()
        for i, (cid, x, y, f) in enumerate(items):
            t = arr[i]
            t.pointerInfo.pointerType = 2          # PT_TOUCH
            t.pointerInfo.pointerId = cid
            t.pointerInfo.pointerFlags = f
            t.pointerInfo.ptPixelLocation = w.POINT(x, y)
            t.touchMask = 0x1                       # CONTACTAREA
            t.rcContact = w.RECT(x - 2, y - 2, x + 2, y + 2)
        u32.InjectTouchInput(len(items), arr)
        self.last = time.monotonic()

    def event(self, action, cid, fx, fy):
        if not self.ok:
            return
        l, t, wd, ht = self.rect
        x, y = int(l + max(0.0, min(1.0, fx)) * (wd - 1)), int(t + max(0.0, min(1.0, fy)) * (ht - 1))
        with self.lock:
            if action == 0:
                self.contacts[cid] = (x, y)
                self._inject(cid, F_DOWN)
            elif action == 1 and cid in self.contacts:
                self.contacts[cid] = (x, y)
                self._inject()
            elif action == 2 and cid in self.contacts:
                self.contacts[cid] = (x, y)
                self._inject(cid, F_UP)
                del self.contacts[cid]

    def release_all(self):
        with self.lock:
            for cid in list(self.contacts):
                self._inject(cid, F_UP)
                del self.contacts[cid]

    def _keepalive(self):
        # Windows cancels held touches that go quiet, so re-send held contacts every 100 ms
        while True:
            time.sleep(0.1)
            with self.lock:
                if self.contacts and time.monotonic() - self.last > 0.09:
                    self._inject()


# ======================================================================= video encoder
# Hardware first (NVIDIA / AMD), then CPU as a last resort. All tuned for low latency, no B-frames.
ENCODERS = {
    "h264_nvenc": ["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ull", "-zerolatency", "1", "-delay", "0",
                   "-rc", "cbr", "-b:v", "12M", "-maxrate", "12M", "-bufsize", "400k", "-forced-idr", "1",
                   "-profile:v", "high"],
    "h264_amf": ["-c:v", "h264_amf", "-usage", "ultralowlatency", "-quality", "speed", "-rc", "cbr",
                 "-b:v", "12M", "-profile:v", "high"],
    "libx264": ["-vf", "hwdownload,format=bgra", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
                "-b:v", "8M", "-maxrate", "8M", "-bufsize", "300k", "-pix_fmt", "yuv420p", "-profile:v", "high"],
}
_encoder = None


def pick_encoder():
    """First encoder that actually works on this PC (checked once, ~1 s)."""
    global _encoder
    if _encoder:
        return _encoder
    for name, opts in ENCODERS.items():
        try:
            r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                                "ddagrab=output_idx=0:framerate=30", *opts, "-frames:v", "5", "-f", "null", "-"],
                               capture_output=True, creationflags=NO_WINDOW, timeout=20)
            if r.returncode == 0:
                _encoder = name
                log(f"video encoder: {name}")
                return name
        except (OSError, subprocess.TimeoutExpired):
            continue
    _encoder = "libx264"
    return _encoder


# ======================================================================= streaming session
class Display:
    def __init__(self, notify=lambda on: None, want_mirror=lambda: False, tablet_size=lambda: (1280, 800)):
        self.notify = notify
        self.want_mirror = want_mirror
        self.tablet_size = tablet_size      # landscape (width, height) of the connected tablet
        self.latency_ms = None
        self.vdd = ParsecVDD()
        self.touch = None
        self.active = False
        self.mirror = False        # True: show the laptop screen instead of adding a new one

    def serve(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", PORT))
        srv.listen(1)
        while True:
            conn, _ = srv.accept()
            try:
                self.session(conn)
            except Exception as e:  # noqa: BLE001 - keep the listener alive whatever happens
                log(f"session ended: {e!r}")
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def session(self, conn):
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 20)
        if self.touch is None:
            self.touch = Touch()
        self.mirror = self.want_mirror()
        self.latency_ms = None
        extend = ParsecVDD.installed() and not self.mirror
        ff = None
        try:
            if extend:                              # a brand-new screen to the right of the laptop
                self.vdd.open()
                self.vdd.add()
                mon = None
                for _ in range(50):                 # wait for Windows to attach the new monitor
                    mon = parsec_display()
                    if mon:
                        break
                    time.sleep(0.1)
                if not mon:
                    raise RuntimeError("virtual monitor did not appear")
                tw, th = self.tablet_size()
                if (mon[3], mon[4]) != (tw, th) and (set_mode(mon[0], tw, th)
                                                     or set_mode(mon[0], 1280, 800)):
                    time.sleep(0.5)
                    mon = parsec_display() or mon
            else:                                   # mirror the laptop screen
                mon = primary_display()
            name, left, top, width, height = mon
            self.touch.rect = (left, top, width, height)
            log(f"virtual monitor {name} at {left},{top} {width}x{height}")
            self.active = True
            self.notify(True)

            ff = self.start_ffmpeg(name, width, height)
            conn.sendall(b"CCV1" + struct.pack(">ii", width, height))
            threading.Thread(target=self.read_touches, args=(conn,), daemon=True).start()
            self.pump(ff, conn)
        finally:
            self.active = False
            if ff and ff.poll() is None:
                ff.kill()
            if self.touch:
                self.touch.release_all()
            if extend:
                self.vdd.remove()
            self.notify(False)
            log("session closed" + (", virtual monitor removed" if extend else ""))

    def start_ffmpeg(self, device, width, height):
        # 45 fps measured best on this tablet (~16-25 ms on screen); bigger mirror frames need 30
        fps = 45 if width * height <= 1280 * 800 else 30
        match = [(a, o) for a, o, name in dxgi_outputs() if name.lower() == device.lower()]
        adapter, idx = match[0] if match else (0, 0)
        log(f"capturing {device}: dxgi adapter {adapter} output {idx}")
        hw = ["-init_hw_device", f"d3d11va=dx:{adapter}", "-filter_hw_device", "dx"] if adapter else []
        enc = pick_encoder()
        args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-fflags", "nobuffer", *hw,
                "-f", "lavfi", "-i", f"ddagrab=output_idx={idx}:framerate={fps}:draw_mouse=1:dup_frames=1",
                *ENCODERS[enc], "-g", "120", "-bf", "0",
                "-bsf:v", "h264_metadata=aud=insert,dump_extra", "-flags", "low_delay", "-flush_packets", "1",
                "-f", "h264", "-"]
        log(f"encoder {enc}, {width}x{height} @ {fps} fps")
        return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                creationflags=NO_WINDOW, bufsize=0)

    def pump(self, ff, conn):
        """Split the H.264 stream into frames (on access-unit delimiters) and send each one."""
        AUD = b"\x00\x00\x00\x01\x09"
        buf = b""
        t0 = time.monotonic()
        fd = ff.stdout.fileno()
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                break
            buf += chunk
            while True:
                end = buf.find(AUD, 5)
                if end < 0:
                    break
                frame, buf = buf[:end], buf[end:]
                if frame.startswith(AUD):          # anything before the first delimiter is dropped
                    pts = int((time.monotonic() - t0) * 1e6)
                    self.t0 = t0
                    conn.sendall(struct.pack(">iq", len(frame), pts) + frame)
        raise ConnectionError("encoder stopped")

    def read_touches(self, conn):
        lat = []
        try:
            f = conn.makefile("rb")
            while True:
                p = f.read(12)
                if len(p) < 12:
                    break
                if p[0] == 9:                          # tablet: "frame <pts> is on screen now"
                    pts = struct.unpack("<q", p[4:12])[0]
                    lat.append((time.monotonic() - self.t0) * 1000 - pts / 1000)
                    if len(lat) >= 10:
                        lat.sort()
                        self.latency_ms = round(lat[len(lat) // 2], 1)
                        log(f"latency encoded->on screen: median {self.latency_ms} ms (min {lat[0]:.1f}, max {lat[-1]:.1f})")
                        lat = []
                    continue
                action, cid, _, x, y = struct.unpack("<BBhff", p)
                self.touch.event(action, cid, x, y)
        except OSError:
            pass
