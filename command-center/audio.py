"""Tablet speaker mode: whatever the laptop plays is streamed to the tablet's speakers over USB.

Laptop: WASAPI loopback of the default speakers (48 kHz, 16-bit stereo, uncompressed) -> adb reverse tcp:8767
Tablet: AudioTrack in low-latency mode. Optionally the laptop speakers are muted while it's on
(loopback still hears the audio), and their old mute state is restored afterwards.
Nothing runs while the feature is off except one idle socket.
"""
import ctypes
import os
import socket
import struct
import threading
import time
from ctypes import POINTER, byref, c_void_p, c_ulong, c_ushort, c_ubyte, Structure

PORT = 8767
RATE, CH = 48000, 2
BLOCK = 480                      # 10 ms of audio per packet


def log(msg):
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    except OSError:
        pass


# ----------------------------------------------------------------- laptop speaker mute (Core Audio)
class GUID(Structure):
    _fields_ = [("a", c_ulong), ("b", c_ushort), ("c", c_ushort), ("d", c_ubyte * 8)]


def _guid(s):
    g = GUID()
    ctypes.oledll.ole32.CLSIDFromString(s, byref(g))
    return g


def _vcall(obj, idx, *types):
    vt = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
    return ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, *types)(vt[idx])


def _endpoint_volume():
    ctypes.windll.ole32.CoInitializeEx(None, 0)   # fine if COM is already set up on this thread
    ole = ctypes.oledll.ole32
    enum = c_void_p()
    ole.CoCreateInstance(byref(_guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")), None, 23,
                         byref(_guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")), byref(enum))
    dev = c_void_p()
    _vcall(enum, 4, ctypes.c_int, ctypes.c_int, POINTER(c_void_p))(enum, 0, 1, byref(dev))  # GetDefaultAudioEndpoint
    vol = c_void_p()
    _vcall(dev, 3, POINTER(GUID), ctypes.c_uint, c_void_p, POINTER(c_void_p))(
        dev, byref(_guid("{5CDF2C82-841E-4546-9722-0CF74078229A}")), 23, None, byref(vol))  # Activate
    return vol


def get_mute():
    v = _endpoint_volume()
    m = ctypes.c_int()
    _vcall(v, 15, POINTER(ctypes.c_int))(v, byref(m))
    return bool(m.value)


def get_volume():
    """Laptop master volume 0..1 (and mute state)."""
    v = _endpoint_volume()
    lvl, m = ctypes.c_float(), ctypes.c_int()
    _vcall(v, 9, POINTER(ctypes.c_float))(v, byref(lvl))
    _vcall(v, 15, POINTER(ctypes.c_int))(v, byref(m))
    return round(lvl.value, 3), bool(m.value)


def set_volume(level):
    v = _endpoint_volume()
    _vcall(v, 7, ctypes.c_float, c_void_p)(v, max(0.0, min(1.0, float(level))), None)


def set_mute(on):
    v = _endpoint_volume()
    _vcall(v, 14, ctypes.c_int, c_void_p)(v, int(bool(on)), None)


# ----------------------------------------------------------------- streaming
MARKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".laptop-muted-by-cc")


class TabSpeaker:
    def __init__(self, enabled=lambda: False, mute_laptop=lambda: True):
        self.enabled = enabled
        self.mute_laptop = mute_laptop
        self.active = False
        self.wake = threading.Event()
        if os.path.exists(MARKER):            # we crashed while the laptop was muted by us: undo it
            try:
                set_mute(False)
                os.remove(MARKER)
                log("restored laptop sound after an unclean stop")
            except OSError:
                pass

    def serve(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", PORT))
        srv.listen(1)
        while True:
            conn, _ = srv.accept()
            try:
                self.session(conn)
            except Exception as e:  # noqa: BLE001 - keep listening whatever happens
                log(f"session ended: {e!r}")
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def changed(self):
        """Call when the on/off setting changes."""
        self.wake.set()

    def session(self, conn):
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.sendall(b"CCA1" + struct.pack(">ii", RATE, CH))
        while True:
            # idle: hold the tablet's connection open, cost nothing, until the feature is switched on
            while not self.enabled():
                self.wake.wait(30)
                self.wake.clear()
                conn.sendall(struct.pack(">i", 0))           # keep-alive (zero-length packet)
            self.stream(conn)

    def stream(self, conn):
        import numpy as np          # only loaded once the feature is actually used
        import soundcard as sc
        spk = sc.default_speaker()
        mic = sc.get_microphone(spk.id, include_loopback=True)
        was_muted = get_mute()
        muted_by_us = False
        self.active = True
        log(f"streaming {spk.name} -> tablet")
        try:
            with mic.recorder(samplerate=RATE, channels=CH, blocksize=BLOCK) as rec:
                if self.mute_laptop() and not was_muted:
                    open(MARKER, "w").close()
                    set_mute(True)
                    muted_by_us = True
                while self.enabled():
                    data = rec.record(numframes=BLOCK)                  # float32, shape (480, 2)
                    pcm = (np.clip(data, -1.0, 1.0) * 32767).astype("<i2").tobytes()
                    conn.sendall(struct.pack(">i", len(pcm)) + pcm)
        finally:
            self.active = False
            if muted_by_us:
                set_mute(False)
                try:
                    os.remove(MARKER)
                except OSError:
                    pass
            log("streaming stopped")
