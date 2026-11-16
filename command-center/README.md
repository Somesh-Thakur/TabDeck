# Tab Command Center

Lenovo Tab M10 HD (TB-X306X, Android 11) as an always-on iPad-style panel for the LOQ 15 laptop.
Everything travels over the USB cable (`adb reverse tcp:8765`), so it uses no Wi-Fi.

## Start
```
powershell -ExecutionPolicy Bypass -File "D:\Lenovo Tab M10 project\command-center\start.ps1"
```
Starts `server.py` hidden. The server detects the tablet over USB on its own (no polling), sets up the tunnel,
forces landscape, keeps the screen on, opens the dashboard and taps once to go full screen and unlock sound.

## Settings app (desktop)
Open **Command Center** from the desktop or Start menu (`open-settings.pyw`). It opens a private, signed-out
Brave app window (Chrome/Edge as fallback) at `http://localhost:8765/settings.html` with a live tablet preview.
Edit: home-screen apps + websites (drag order, rename), widgets (show/hide/order), dock actions, wallpaper,
accent, clock, notification sound/volume/duration, tablet brightness, mic on/off + mode, stats refresh rate,
start with Windows. Saved in `settings.json` / `apps.json` and pushed to the tablet instantly.
About 240 MB while the window is open, 0 when closed.

## Tablet app (`../tablet-app`)
`CommandCenter.apk` (~60 KB) is the tablet's **home screen**: full-screen dashboard in a WebView (no Chrome),
plus native second-screen mode. Build + install: `tablet-app\build.ps1 -Install` (uses `tools\android-sdk`, JDK 21).
Back button: closes sheets / leaves second screen. Press Back 5× fast for Android Settings.

## Second screen (`display.py`)
Dock button **Second Screen** (or settings app › Second Screen). Pipeline: Parsec virtual display (added only while
on) → ffmpeg `ddagrab` GPU capture → `h264_nvenc` → USB (`adb reverse tcp:8766`) → tablet MediaCodec
(MediaTek `vdec-lowlatency`) → screen. Touches come back as real Windows multi-touch.
Measured: 45 fps, ~16–25 ms encoded→on screen, ffmpeg ~0.5 % CPU / ~90 MB only while active.
Without the Parsec driver (`tools\parsec-vdd\parsec-vdd-0.45.0.0.exe`, signed by Parsec) it mirrors the laptop screen.
Three-finger tap on the tablet returns to the dashboard. Log: `display.log`.

## Tablet speaker (`audio.py`)
Dock button **Tab Speaker** (purple, lit when on) or settings app › Tablet › Sound. WASAPI loopback of the
default speakers → raw 48 kHz PCM over USB (`adb reverse tcp:8767`) → tablet AudioTrack (low-latency).
Optionally mutes the laptop speakers meanwhile and restores them (also after a crash, via a marker file).
~0.7 % CPU while on; nothing but an idle socket while off. Log: `audio.log`.

## Claude Code on the tablet (`claude_hook.py`)
Hooks in `~/.claude/settings.json` (Stop, Notification, PermissionRequest) call `claude_hook.py`:
- Claude finishes → coral banner + chime with the start of its reply.
- Claude needs permission → big **Allow / Deny** card on the tablet (pulls you out of second-screen mode).
  No answer within 45 s, or Command Center not running → Claude shows its normal prompt as usual.
Test: `python test_claude_hook.py`.

## Now Playing (`media.py`)
Reads Windows' media session (any app: Spotify, Brave/Chrome tabs, Spindle…): title, artist, artwork, live progress.
Play/next/previous control that app directly. Polls once a second only while the dashboard is open.

## Laptop off → dim clock
The tablet app switches to a near-black clock at minimum backlight when the laptop disappears for 15 s,
drifts it every minute (no burn-in), lets the screen sleep if the tab battery < 15 % and not charging, and returns
to the dashboard by itself when the laptop is back.

## Discord buttons
Mute / deafen appear in the dock only while Discord runs. One-time setup in Discord › Settings › Keybinds:
**Toggle Mute = Ctrl+Shift+Alt+M**, **Toggle Deafen = Ctrl+Shift+Alt+D**.

## Tools (trackpad · keyboard · gamepad · sign) — `web/tools.js`, `inputs.py`
Dock button **Tools** (or `POST /tools {"tab":"sign"}` to open one remotely, `null` to close).
- Input arrives as batched JSON at `POST /input` (one request per screen frame) and is injected with `SendInput`
  (scan codes, so games see it; text as Unicode so any language works).
- Gamepad: keyboard mapping by default (stick = WASD, A = Space, B = Ctrl, X = E, Y = Q, LB/RB = 1/2, LT/RT = R/F,
  D-pad = arrows, Start = Esc, Back = Tab). If `pip install vgamepad` (+ its ViGEmBus driver) is present it becomes a
  real virtual Xbox 360 controller with analog stick.
- Signature: `POST /signature {png}` saves to `Pictures\TabDeck Signatures\` and puts it on the clipboard as PNG
  (transparent) + bitmap on white (`sig-clipboard.ps1`).

## Themes
CSS files in `themes/` (built-ins) plus uploads saved as `themes/user-*.css`. Endpoints: `GET /themes`,
`GET /themes/<file>`, `POST /themes/upload {name, css}`, `POST /themes/apply {file}`, `POST /themes/delete {file}`.
Uploads are sanitised (`@import` and http(s) URLs removed, max 256 KB). The dashboard loads the active theme
after a `<style id="userVars">` block, so themes override the user's wallpaper/accent. Guide: `../THEMING.md`.

## History widget
`HISTORY` keeps 30 min of (time, cpu, gpu, ram) at 1 s; sent (every 2nd point) in the `hello` event, then live.

## Tablet debloat
`tablet-app\debloat.ps1` removed 36 apps for the user (reversible): undo with `tablet-app\restore.ps1`.

## Footprint on the laptop (measured)
One `pythonw.exe` process: about 6–7 MB of RAM in use, about 0.01 % CPU, 0 disk activity.
Stats are only collected while the tablet page is connected. The GPU is read in-process through NVML every 3 s.

## Features
- Activity rings (CPU / GPU / RAM), GPU temperature, power and VRAM, network speed with sparkline, laptop and tab battery
- Media controls and volume, dock: Lock PC, Snip, Task Manager, Show desktop
- **Apps**: tap to launch on the laptop. **Edit** (or long-press an icon) to remove apps, or **+ Add App** to pick any
  Start-menu app (real 256 px icons extracted automatically). Saved in `apps.json`.
- **Notifications** with a chime and banner: POST to `http://localhost:8765/notify`
  ```
  curl -X POST localhost:8765/notify -d "{\"title\":\"Build done\",\"body\":\"All tests passed\",\"level\":\"done\"}"
  ```
  levels: `info`, `done`, `warn`, `error`. The bell opens the history.
- **Tab Mic**: tablet microphone → scrcpy (raw PCM over USB) → **CABLE Input** → apps pick **"CABLE Output"** as their mic.
  `mic-route.ps1` pins scrcpy's output to the cable every time the mic starts, so it never plays from the speakers.
  Costs ~14 MB RAM only while the mic is on.

## Files
- `server.py`: stats, actions, app launcher, notifications, mic (stdlib + psutil)
- `icons.ps1`: extracts app icons, only runs when you add an app
- `web/index.html`: the tablet UI
- `../tools/platform-tools/`: Google adb
