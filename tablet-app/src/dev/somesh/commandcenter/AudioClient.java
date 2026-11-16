package dev.somesh.commandcenter;

import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;

import java.io.BufferedInputStream;
import java.io.DataInputStream;
import java.net.InetSocketAddress;
import java.net.Socket;

/**
 * Tablet-speaker mode: plays the laptop's sound (raw 16-bit PCM over USB, adb reverse tcp:8767).
 * The connection idles at zero cost until the laptop switches the feature on.
 *
 * Laptop -> tablet: "CCA1" | int rate | int channels, then packets: int length | PCM bytes (length 0 = keep-alive)
 */
class AudioClient extends Thread {
    private volatile boolean running = true;
    private volatile Socket socket;

    AudioClient() { super("cc-audio"); setPriority(MAX_PRIORITY); }

    void shutdown() {
        running = false;
        try { if (socket != null) socket.close(); } catch (Exception ignored) { }
    }

    @Override public void run() {
        while (running) {
            try { session(); } catch (Exception ignored) { }
            try { if (socket != null) socket.close(); } catch (Exception ignored) { }
            if (running) try { Thread.sleep(1500); } catch (InterruptedException ignored) { }
        }
    }

    private void session() throws Exception {
        Socket s = new Socket();
        s.setTcpNoDelay(true);
        s.connect(new InetSocketAddress("127.0.0.1", 8767), 1500);
        socket = s;
        DataInputStream in = new DataInputStream(new BufferedInputStream(s.getInputStream(), 1 << 15));
        byte[] magic = new byte[4];
        in.readFully(magic);
        if (magic[0] != 'C' || magic[1] != 'C' || magic[2] != 'A' || magic[3] != '1') throw new IllegalStateException();
        int rate = in.readInt(), ch = in.readInt();
        int chMask = ch == 1 ? AudioFormat.CHANNEL_OUT_MONO : AudioFormat.CHANNEL_OUT_STEREO;
        int bytesPerMs = rate * ch * 2 / 1000;
        int min = AudioTrack.getMinBufferSize(rate, chMask, AudioFormat.ENCODING_PCM_16BIT);

        AudioTrack track = null;
        byte[] buf = new byte[1 << 14];
        try {
            while (running) {
                int len = in.readInt();
                if (len == 0) {                     // keep-alive while the feature is off: free the speaker
                    if (track != null) { track.stop(); track.release(); track = null; }
                    continue;
                }
                if (len > buf.length) buf = new byte[len];
                in.readFully(buf, 0, len);
                if (track == null) {
                    track = new AudioTrack.Builder()
                        .setAudioAttributes(new AudioAttributes.Builder()
                            .setUsage(AudioAttributes.USAGE_MEDIA)
                            .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                        .setAudioFormat(new AudioFormat.Builder()
                            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                            .setSampleRate(rate).setChannelMask(chMask).build())
                        .setBufferSizeInBytes(Math.max(min, 40 * bytesPerMs))
                        .setTransferMode(AudioTrack.MODE_STREAM)
                        .setPerformanceMode(AudioTrack.PERFORMANCE_MODE_LOW_LATENCY)
                        .build();
                    track.play();
                }
                // if we've fallen behind (clock drift, hiccup), skip ahead instead of letting delay grow
                if (in.available() > 80 * bytesPerMs) continue;
                track.write(buf, 0, len);
            }
        } finally {
            if (track != null) { try { track.stop(); } catch (Exception ignored) { } track.release(); }
        }
    }
}
