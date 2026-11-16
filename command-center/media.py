"""Now Playing: reads Windows' media session (what the volume flyout shows) - any app: Spotify,
Brave/Chrome tabs, Spindle, YouTube... - and controls that exact app (play/pause/next/previous)."""
import asyncio
import hashlib
import threading
import time

from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
from winrt.windows.storage.streams import DataReader

APP_NAMES = {"spotify": "Spotify", "brave": "Brave", "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox",
             "zunemusic": "Media Player", "vlc": "VLC", "applemusic": "Apple Music", "discord": "Discord"}
STATUS = {4: "playing", 5: "paused", 3: "stopped"}


def app_name(aumid):
    a = (aumid or "").lower()
    for k, v in APP_NAMES.items():
        if k in a:
            return v
    return (aumid or "").split("!")[-1].split(".")[0][:20] or "Media"


class NowPlaying:
    def __init__(self, on_change, active=lambda: True):
        self.on_change = on_change
        self.active = active
        self.loop = asyncio.new_event_loop()
        self.manager = None
        self.state = {"playing": False, "title": None}
        self.art = (None, b"")            # (key, png/jpeg bytes)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._main())

    async def _main(self):
        self.manager = await Manager.request_async()
        last = None
        while True:
            await asyncio.sleep(1)
            if not self.active():
                continue
            try:
                s = await self._read()
            except Exception:  # noqa: BLE001 - an app closing mid-read is normal
                s = {"playing": False, "title": None}
            try:
                import audio
                s["vol"], s["muted"] = audio.get_volume()      # laptop master volume for the volume bar
            except Exception:  # noqa: BLE001
                pass
            key = {k: v for k, v in s.items() if k not in ("pos", "at")}
            if key != last or s.get("playing"):
                if key != last or int(time.time()) % 5 == 0:   # position resync every 5 s while playing
                    self.state = s
                    self.on_change(s)
                last = key

    async def _read(self):
        sess = self.manager.get_current_session()
        if not sess:
            return {"playing": False, "title": None}
        p = await sess.try_get_media_properties_async()
        tl, pb = sess.get_timeline_properties(), sess.get_playback_info()
        status = STATUS.get(int(pb.playback_status), "stopped")
        art_key = None
        if p.thumbnail is not None:
            art_key = hashlib.sha1(f"{p.title}|{p.artist}|{p.album_title}".encode()).hexdigest()[:12]
            if art_key != self.art[0]:
                self.art = (art_key, await self._thumb(p.thumbnail))
        pos = tl.position.total_seconds() if tl.position else 0
        # browsers update the position rarely: extrapolate from when it was last reported
        if status == "playing" and tl.last_updated_time:
            try:
                pos += max(0.0, time.time() - tl.last_updated_time.timestamp())
            except Exception:  # noqa: BLE001
                pass
        dur = tl.end_time.total_seconds() if tl.end_time else 0
        c = pb.controls                     # what the playing app actually supports
        caps = {"next": bool(c.is_next_enabled), "prev": bool(c.is_previous_enabled),
                "seek": bool(c.is_playback_position_enabled)}
        return {"playing": status == "playing", "status": status, "title": p.title or None,
                "artist": p.artist or p.album_artist or "", "album": p.album_title or "",
                "app": app_name(sess.source_app_user_model_id), "art": art_key if self.art[1] else None,
                "pos": round(min(pos, dur) if dur else pos, 1), "dur": round(dur, 1), "at": time.time(), "caps": caps}

    @staticmethod
    async def _thumb(ref):
        try:
            stream = await ref.open_read_async()
            size = int(stream.size)
            reader = DataReader(stream.get_input_stream_at(0))
            await reader.load_async(size)
            buf = bytearray(size)
            reader.read_bytes(buf)
            return bytes(buf)
        except Exception:  # noqa: BLE001
            return b""

    def control(self, action, value=None):
        async def go():
            sess = self.manager and self.manager.get_current_session()
            if not sess:
                return False
            if action == "seek":            # seconds -> 100 ns ticks
                ok = bool(await sess.try_change_playback_position_async(int(float(value) * 10_000_000)))
                if ok and self.state.get("title"):
                    self.state = {**self.state, "pos": float(value), "at": time.time()}
                    self.on_change(self.state)
                return ok
            fn = {"play": sess.try_toggle_play_pause_async, "next": sess.try_skip_next_async,
                  "prev": sess.try_skip_previous_async}.get(action)
            return bool(fn and await fn())
        try:
            return asyncio.run_coroutine_threadsafe(go(), self.loop).result(3)
        except Exception:  # noqa: BLE001
            return False
