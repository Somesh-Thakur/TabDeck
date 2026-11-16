package dev.somesh.commandcenter;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.AudioManager;
import android.speech.tts.TextToSpeech;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

/**
 * Command Center for the tablet: a home-screen app that shows the laptop's dashboard
 * full screen (no browser bars) and switches into a low-latency second-screen mode.
 */
public class MainActivity extends Activity {
    static final String URL = "http://127.0.0.1:8765/?app=1";
    static final String OFFLINE =
        "<html><body style='margin:0;height:100vh;display:flex;align-items:center;justify-content:center;"
      + "flex-direction:column;background:#06060a;color:#8e8e93;font-family:sans-serif'>"
      + "<div style='width:56px;height:56px;border-radius:50%;border:4px solid #2c2c2e;border-top-color:#0a84ff;"
      + "animation:s 1s linear infinite'></div><p style='margin-top:22px;font-size:17px'>Waiting for laptop…</p>"
      + "<p style='font-size:13px;color:#48484a'>Plug in the USB cable. Command Center starts by itself.</p>"
      + "<style>@keyframes s{to{transform:rotate(360deg)}}</style></body></html>";

    /** Laptop off / asleep: a near-black clock at minimum backlight. Drifts a little each minute (no burn-in). */
    static final String CLOCK =
        "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head>"
      + "<body style='margin:0;height:100vh;background:#000;overflow:hidden;font-family:sans-serif;cursor:none'>"
      + "<div id='c' style='position:absolute;text-align:center;transition:all 2s ease'>"
      + "<div id='t' style='font-size:180px;font-weight:200;letter-spacing:-6px;color:#3a3a3e;line-height:1'></div>"
      + "<div id='d' style='font-size:24px;color:#26262a;margin-top:10px;font-weight:500'></div></div>"
      + "<script>function f(){var n=new Date(),h=n.getHours()%12||12,m=('0'+n.getMinutes()).slice(-2);"
      + "document.getElementById('t').textContent=h+':'+m;"
      + "document.getElementById('d').textContent=n.toLocaleDateString([], {weekday:'long',day:'numeric',month:'long'});}"
      + "function p(){var c=document.getElementById('c'),w=innerWidth,H=innerHeight,cw=c.offsetWidth,ch=c.offsetHeight;"
      + "c.style.left=((w-cw)/2+(Math.random()*60-30))+'px';c.style.top=((H-ch)/2+(Math.random()*40-20))+'px';}"
      + "f();p();setInterval(f,1000);setInterval(p,60000);</script></body></html>";

    final Handler ui = new Handler(Looper.getMainLooper());
    boolean clockMode;
    WebView web;
    SurfaceView screen;
    DisplayClient display;
    AudioClient speaker;
    boolean online, displayOn;
    TextToSpeech tts;
    PermissionRequest pendingCam;
    int savedVolume = -1;
    long lastBack; int backCount;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        Window w = getWindow();
        w.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
                 | WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                 | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        w.getAttributes().layoutInDisplayCutoutMode =
            WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
        w.setBackgroundDrawableResource(android.R.color.black);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);   // notification chime works without a tap
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        web.setBackgroundColor(Color.BLACK);
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        web.addJavascriptInterface(new Bridge(), "CC");
        web.setWebChromeClient(new WebChromeClient() {
            // camera (study-mode phone watch / away lock): only our own dashboard may use the camera
            @Override public void onPermissionRequest(PermissionRequest r) {
                ui.post(() -> {
                    String o = String.valueOf(r.getOrigin());
                    boolean ours = o.startsWith("http://127.0.0.1:8765") || o.startsWith("http://localhost:8765");
                    if (!ours) { r.deny(); return; }
                    if (checkSelfPermission(android.Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                        r.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
                    } else {
                        pendingCam = r;
                        requestPermissions(new String[]{android.Manifest.permission.CAMERA}, 7);
                    }
                });
            }
        });
        web.setWebViewClient(new WebViewClient() {
            @Override public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (r.isForMainFrame()) goOffline();
            }
            @Override public void onPageFinished(WebView v, String url) {
                if (url != null && url.startsWith("http://127.0.0.1")) online = true;
            }
        });

        screen = new SurfaceView(this);
        screen.setVisibility(View.GONE);
        screen.getHolder().addCallback(new SurfaceHolder.Callback() {
            @Override public void surfaceCreated(SurfaceHolder h) {
                if (displayOn) startDisplay();
            }
            @Override public void surfaceChanged(SurfaceHolder h, int f, int wd, int ht) {}
            @Override public void surfaceDestroyed(SurfaceHolder h) { stopDisplay(); }
        });
        screen.setOnTouchListener(this::onScreenTouch);

        root.addView(web, new FrameLayout.LayoutParams(-1, -1));
        root.addView(screen, new FrameLayout.LayoutParams(-1, -1));
        setContentView(root);
        immersive();
        web.loadUrl(URL);
        speaker = new AudioClient();       // idles until the laptop turns tablet-speaker mode on
        speaker.start();
    }

    @Override public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        if (code != 7 || pendingCam == null) return;
        if (res.length > 0 && res[0] == PackageManager.PERMISSION_GRANTED)
            pendingCam.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
        else pendingCam.deny();
        pendingCam = null;
    }

    /** Study mode: speak through Android's own voice, loud. */
    void say(String text) {
        if (tts == null) {
            tts = new TextToSpeech(this, st -> { if (st == TextToSpeech.SUCCESS) { tts.setSpeechRate(1.05f); tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "cc"); } });
            return;
        }
        tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "cc");
    }

    /** Alarm on: media volume to max (remembering the old level). Off: restore it. */
    void alarm(boolean on) {
        AudioManager am = (AudioManager) getSystemService(AUDIO_SERVICE);
        if (on && savedVolume < 0) {
            savedVolume = am.getStreamVolume(AudioManager.STREAM_MUSIC);
            am.setStreamVolume(AudioManager.STREAM_MUSIC, am.getStreamMaxVolume(AudioManager.STREAM_MUSIC), 0);
        } else if (!on && savedVolume >= 0) {
            am.setStreamVolume(AudioManager.STREAM_MUSIC, savedVolume, 0);
            savedVolume = -1;
        }
    }

    void goOffline() { showClock(); }

    /** Laptop gone: dim clock, minimum backlight, and quietly wait for the laptop to come back. */
    void showClock() {
        if (clockMode) return;
        if (displayOn) setDisplay(false);
        clockMode = true;
        online = false;
        web.loadDataWithBaseURL(null, CLOCK, "text/html", "utf-8", null);
        setBrightness(0.01f);
        ui.removeCallbacksAndMessages(null);
        ui.postDelayed(this::checkLaptop, 4000);
    }

    void exitClock() {
        if (!clockMode) return;
        clockMode = false;
        setBrightness(-1f);                                   // back to the normal brightness
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        web.loadUrl(URL);
    }

    void setBrightness(float v) {
        WindowManager.LayoutParams lp = getWindow().getAttributes();
        lp.screenBrightness = v;
        getWindow().setAttributes(lp);
    }

    /** Every few seconds while on the clock: is the laptop back? Also lets the screen sleep on low battery. */
    void checkLaptop() {
        if (!clockMode) return;
        new Thread(() -> {
            boolean up = false;
            try {
                java.net.HttpURLConnection c = (java.net.HttpURLConnection)
                    new java.net.URL("http://127.0.0.1:8765/settings").openConnection();
                c.setConnectTimeout(1200);
                c.setReadTimeout(1200);
                up = c.getResponseCode() == 200;
                c.disconnect();
            } catch (Exception ignored) { }
            final boolean back = up;
            ui.post(() -> {
                if (back) { exitClock(); return; }
                android.content.Intent b = registerReceiver(null,
                    new android.content.IntentFilter(android.content.Intent.ACTION_BATTERY_CHANGED));
                int level = b == null ? 100 : b.getIntExtra(android.os.BatteryManager.EXTRA_LEVEL, 100);
                boolean charging = b != null && b.getIntExtra(android.os.BatteryManager.EXTRA_PLUGGED, 0) != 0;
                if (level < 15 && !charging) getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                else getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                ui.postDelayed(this::checkLaptop, 4000);
            });
        }).start();
    }

    void immersive() {
        getWindow().getDecorView().setSystemUiVisibility(
              View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_FULLSCREEN
            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN);
    }

    @Override public void onWindowFocusChanged(boolean f) { super.onWindowFocusChanged(f); if (f) immersive(); }

    @Override public void onResume() { super.onResume(); web.onResume(); immersive(); if (!online && !displayOn && !clockMode) web.loadUrl(URL); }

    /** Back closes sheets on the dashboard / leaves display mode. Press it 5 times fast to reach Android Settings. */
    @Override public void onBackPressed() {
        long now = System.currentTimeMillis();
        backCount = now - lastBack < 600 ? backCount + 1 : 1;
        lastBack = now;
        if (backCount >= 5) { backCount = 0; startActivity(new Intent(Settings.ACTION_SETTINGS)); return; }
        if (displayOn) { setDisplay(false); return; }
        web.evaluateJavascript("window.ccBack&&ccBack()", null);
    }

    // ------------------------------------------------------------- second-screen mode
    void setDisplay(boolean on) {
        if (on == displayOn) return;
        displayOn = on;
        if (on) {
            screen.setVisibility(View.VISIBLE);           // surfaceCreated -> startDisplay()
        } else {
            stopDisplay();
            screen.setVisibility(View.GONE);
        }
        web.evaluateJavascript("window.ccDisplay&&ccDisplay(" + on + ")", null);
    }

    void startDisplay() {
        stopDisplay();
        display = new DisplayClient(screen.getHolder().getSurface(), () -> ui.post(() -> {}));
        display.start();
    }

    void stopDisplay() {
        if (display != null) { display.shutdown(); display = null; }
    }

    int threeFingerDown;
    boolean onScreenTouch(View v, MotionEvent e) {
        // three-finger tap = back to the dashboard
        if (e.getActionMasked() == MotionEvent.ACTION_POINTER_DOWN && e.getPointerCount() == 3) {
            threeFingerDown = 1;
        } else if (e.getActionMasked() == MotionEvent.ACTION_UP && threeFingerDown == 1) {
            threeFingerDown = 0;
            setDisplay(false);
            return true;
        }
        if (display != null && threeFingerDown == 0) display.sendTouch(e, v.getWidth(), v.getHeight());
        return true;
    }

    @Override protected void onDestroy() { stopDisplay(); alarm(false); if (tts != null) tts.shutdown(); if (speaker != null) speaker.shutdown(); super.onDestroy(); }

    // ------------------------------------------------------------- JS bridge (window.CC)
    class Bridge {
        @JavascriptInterface public void setDisplay(boolean on) { ui.post(() -> MainActivity.this.setDisplay(on)); }
        @JavascriptInterface public boolean isDisplay() { return displayOn; }
        @JavascriptInterface public void androidSettings() { ui.post(() -> startActivity(new Intent(Settings.ACTION_SETTINGS))); }
        @JavascriptInterface public void reload() { ui.post(() -> web.loadUrl(URL)); }
        @JavascriptInterface public String version() { return "1.2"; }
        @JavascriptInterface public void say(String t) { ui.post(() -> MainActivity.this.say(t)); }
        @JavascriptInterface public void alarm(boolean on) { ui.post(() -> MainActivity.this.alarm(on)); }
        @JavascriptInterface public void laptopGone() { ui.post(MainActivity.this::showClock); }
    }
}
