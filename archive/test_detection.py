"""Headless test: wait 3 seconds, then detect and print the focused window.

Usage: give yourself three seconds to switch to an app. A sound plays the
moment detection fires, so you know when to switch back to the terminal.
"""

import os
import shutil
import subprocess
import time

import get_desktop_state

DELAY_SECONDS = 3


def _play_beep():
    """Best-effort sound: paplay with the freedesktop bell, else fall back."""
    bell = "/usr/share/sounds/freedesktop/stereo/bell.oga"
    try:
        if shutil.which("paplay") and os.path.exists(bell):
            subprocess.run(["paplay", bell], check=False, timeout=5)
        elif shutil.which("canberra-gtk-play"):
            subprocess.run(["canberra-gtk-play", "-i", "bell"], check=False, timeout=5)
        else:
            print("\a", end="", flush=True)  # terminal bell as last resort
    except Exception:
        print("\a", end="", flush=True)


print(f"Switch to another app now — detecting in {DELAY_SECONDS} seconds...")
time.sleep(DELAY_SECONDS)

_play_beep()

state = get_desktop_state.get_desktop_state()
get_desktop_state._print_state(state)
