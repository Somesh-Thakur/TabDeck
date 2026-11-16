package dev.somesh.commandcenter;

import android.media.MediaCodec;
import android.media.MediaFormat;
import android.view.MotionEvent;
import android.view.Surface;

import java.io.BufferedInputStream;
import java.io.DataInputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.concurrent.LinkedBlockingQueue;

/**
 * Second-screen client. Connects over USB (adb reverse) to the laptop, hardware-decodes the
 * H.264 stream straight onto the screen and sends touches back.
 *
 * Laptop -> tablet:  "CCV1" | int width | int height, then per frame: int length | long ptsUs | bytes
 * Tablet -> laptop:  12-byte touch packets: byte action(0 down,1 move,2 up) | byte id | short 0 | float x | float y (0..1)
 */
class DisplayClient extends Thread {
    private final Surface surface;
    private final Runnable onState;
    private volatile boolean running = true;
    private volatile Socket socket;
    private volatile MediaCodec codec;
    private final LinkedBlockingQueue<byte[]> outbox = new LinkedBlockingQueue<>(256);

    DisplayClient(Surface surface, Runnable onState) {
        super("cc-display");
        this.surface = surface;
        this.onState = onState;
    }

    void shutdown() {
        running = false;
        try { if (socket != null) socket.close(); } catch (Exception ignored) {}
        interrupt();
    }

    @Override public void run() {
        while (running) {
            try {
                session();
            } catch (Exception e) {
                // laptop not ready yet / cable unplugged: try again shortly
            } finally {
                release();
            }
            if (running) try { Thread.sleep(700); } catch (InterruptedException ignored) { }
        }
    }

    private void session() throws Exception {
        Socket s = new Socket();
        s.setTcpNoDelay(true);
        s.setReceiveBufferSize(1 << 20);
        s.connect(new InetSocketAddress("127.0.0.1", 8766), 1500);
        socket = s;
        DataInputStream in = new DataInputStream(new BufferedInputStream(s.getInputStream(), 1 << 17));
        OutputStream out = s.getOutputStream();

        byte[] magic = new byte[4];
        in.readFully(magic);
        if (magic[0] != 'C' || magic[1] != 'C' || magic[2] != 'V' || magic[3] != '1') throw new IllegalStateException("bad stream");
        int w = in.readInt(), h = in.readInt();

        MediaCodec c = MediaCodec.createDecoderByType(MediaFormat.MIMETYPE_VIDEO_AVC);
        boolean lowLatency = false;
        try {
            lowLatency = c.getCodecInfo().getCapabilitiesForType(MediaFormat.MIMETYPE_VIDEO_AVC)
                .isFeatureSupported(android.media.MediaCodecInfo.CodecCapabilities.FEATURE_LowLatency);
        } catch (Exception ignored) { }
        boolean mtk = c.getName().toLowerCase().contains("mtk");
        try {
            MediaFormat f = format(w, h, lowLatency, true);
            if (mtk) f.setInteger("vdec-lowlatency", 1);   // MediaTek: output each frame as soon as it's decoded
            c.configure(f, surface, null, 0);
        } catch (Exception e) {           // e.g. MediaTek rejects optional keys: retry with the bare minimum
            c.reset();
            c.configure(format(w, h, false, false), surface, null, 0);
        }
        c.start();
        codec = c;

        Thread drain = new Thread(() -> {               // show every decoded frame immediately
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            int n = 0;
            while (running && codec == c) {
                try {
                    int idx = c.dequeueOutputBuffer(info, 20000);
                    if (idx >= 0) {
                        c.releaseOutputBuffer(idx, true);
                        if (++n % 30 == 0) {            // tell the laptop when this frame hit the screen (latency stats)
                            ByteBuffer p = ByteBuffer.allocate(12).order(ByteOrder.LITTLE_ENDIAN);
                            p.put((byte) 9).put((byte) 0).putShort((short) 0).putLong(info.presentationTimeUs);
                            outbox.offer(p.array());
                        }
                    }
                } catch (Exception e) { break; }
            }
        }, "cc-render");
        drain.start();

        Thread writer = new Thread(() -> {              // touches go out on their own thread
            try {
                while (running && !s.isClosed()) out.write(outbox.take());
            } catch (Exception ignored) { }
        }, "cc-touch");
        writer.start();
        onState.run();

        byte[] buf = new byte[1 << 18];
        while (running) {
            int len = in.readInt();
            long pts = in.readLong();
            if (len > buf.length) buf = new byte[len + (1 << 16)];
            in.readFully(buf, 0, len);
            int ii = c.dequeueInputBuffer(100000);
            if (ii < 0) continue;                       // decoder busy: drop this frame rather than lag
            ByteBuffer b = c.getInputBuffer(ii);
            b.clear();
            b.put(buf, 0, len);
            c.queueInputBuffer(ii, 0, len, pts, 0);
        }
    }

    private static MediaFormat format(int w, int h, boolean lowLatency, boolean extras) {
        MediaFormat f = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, w, h);
        f.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 1 << 20);
        if (lowLatency) f.setInteger(MediaFormat.KEY_LOW_LATENCY, 1);
        if (extras) {
            f.setInteger(MediaFormat.KEY_PRIORITY, 0);          // real-time
            f.setInteger(MediaFormat.KEY_OPERATING_RATE, 120);
        }
        return f;
    }

    private void release() {
        MediaCodec c = codec;
        codec = null;
        if (c != null) { try { c.stop(); } catch (Exception ignored) {} try { c.release(); } catch (Exception ignored) {} }
        try { if (socket != null) socket.close(); } catch (Exception ignored) {}
        outbox.clear();
    }

    void sendTouch(MotionEvent e, int w, int h) {
        if (codec == null) return;
        int a = e.getActionMasked();
        if (a == MotionEvent.ACTION_MOVE) {
            for (int i = 0; i < e.getPointerCount(); i++) queue(1, e.getPointerId(i), e.getX(i) / w, e.getY(i) / h);
        } else if (a == MotionEvent.ACTION_DOWN || a == MotionEvent.ACTION_POINTER_DOWN) {
            int i = e.getActionIndex();
            queue(0, e.getPointerId(i), e.getX(i) / w, e.getY(i) / h);
        } else if (a == MotionEvent.ACTION_UP || a == MotionEvent.ACTION_POINTER_UP || a == MotionEvent.ACTION_CANCEL) {
            int i = e.getActionIndex();
            queue(2, e.getPointerId(i), e.getX(i) / w, e.getY(i) / h);
        }
    }

    private void queue(int action, int id, float x, float y) {
        ByteBuffer p = ByteBuffer.allocate(12).order(ByteOrder.LITTLE_ENDIAN);
        p.put((byte) action).put((byte) id).putShort((short) 0).putFloat(x).putFloat(y);
        outbox.offer(p.array());
    }
}
