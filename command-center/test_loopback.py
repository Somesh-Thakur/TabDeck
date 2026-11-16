"""Does WASAPI loopback still capture audio while the laptop speakers are muted?
Plays a very quiet tone with the speakers muted (so nothing is heard), records the loopback, restores mute."""
import threading
import time

import numpy as np
import soundcard as sc

import audio

was = audio.get_mute()
audio.set_mute(True)
print("speakers muted for the test (was muted before:", was, ")")
spk = sc.default_speaker()
mic = sc.get_microphone(spk.id, include_loopback=True)
tone = (0.05 * np.sin(2 * np.pi * 440 * np.arange(48000 * 2) / 48000)).astype("float32")
tone = np.stack([tone, tone], axis=1)
try:
    with mic.recorder(samplerate=48000, channels=2) as rec:
        t = threading.Thread(target=lambda: spk.play(tone, samplerate=48000))
        t.start()
        time.sleep(0.3)
        data = rec.record(numframes=48000)
        t.join()
    print("captured peak while muted: %.4f (tone peak 0.05)" % float(np.abs(data).max()))
finally:
    audio.set_mute(was)
    print("speaker mute restored to:", audio.get_mute())
