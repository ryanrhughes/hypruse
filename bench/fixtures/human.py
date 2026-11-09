"""A person at the desk: types lines into whichever window has keyboard
focus, about seven characters a second.

Each line is logged to $BENCH_STATE/typed.txt once its Return is pressed,
so a check can compare what they typed with what reached their own window.
If the agent takes focus, their keys land somewhere else and the two
differ. On TERM it finishes the line it is on, logs it and exits, so every
trial compares at least one whole line.

It types like a physical keyboard: the layout's real keymap and real
keycodes. An earlier version used wtype, whose throwaway one-key keymaps
became the seat's active keymap while it typed, so Hyprland's sendshortcut
(which looks key names up in that keymap) failed for the agent. That was
the simulator's fault, not something a real keyboard does. The lines use
only lowercase letters, digits and spaces, so no key needs Shift.

Run with the fork's Python: it borrows hypruse's Wayland keyboard.
"""

import os
import signal
import time

from hypruse import hyprctl, keymap
from hypruse.wire import VirtualKeyboard

STATE = os.environ["BENCH_STATE"]
LINES = [
    "notes for thursday ask about the q3 numbers",
    "check the dock firmware on the n1x",
    "lunch with the delivery team at noon",
    "draft the release notes before friday",
]

stop = False


def on_term(_signum: int, _frame: object) -> None:
    global stop
    stop = True


def main() -> None:
    with open(os.path.join(STATE, "human.pid"), "w") as f:
        f.write(str(os.getpid()))
    signal.signal(signal.SIGTERM, on_term)

    real = keymap.real_keys(*hyprctl.active_layout())
    codes = {ch: real.code(ch) for line in LINES for ch in line}
    codes[" "] = real.code("space")
    enter = real.code("Return")
    missing = [ch for ch, code in codes.items() if code is None]
    if missing or enter is None:
        raise SystemExit(f"the layout has no unshifted key for {missing}")

    kb = VirtualKeyboard()
    while True:
        for line in LINES:
            for ch in line:
                kb.press_codes(real.text, [codes[ch]])
                time.sleep(0.14)
            kb.press_codes(real.text, [enter])
            with open(os.path.join(STATE, "typed.txt"), "a") as f:
                f.write(line + "\n")
            if stop:
                return
            time.sleep(1)


if __name__ == "__main__":
    main()
