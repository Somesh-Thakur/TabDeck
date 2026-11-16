"""Quick self-test: add a Parsec virtual screen, set it to 1280x800, list it, then remove it."""
import time

import display

v = display.ParsecVDD()
print("installed:", v.installed())
v.open()
print("driver version:", v._ioctl(display.IOCTL_VERSION))
print("added index:", v.add())
m = None
for _ in range(50):
    m = display.parsec_display()
    if m:
        break
    time.sleep(0.1)
print("monitor:", m)
if m:
    print("set 1280x800:", display.set_mode(m[0], 1280, 800))
    time.sleep(0.8)
    print("now:", display.parsec_display())
    print("dxgi outputs:", display.dxgi_outputs())
v.remove()
time.sleep(1.5)
print("after remove:", display.parsec_display())
