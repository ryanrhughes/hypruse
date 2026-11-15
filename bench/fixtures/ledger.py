"""Bench Ledger: one Amount field and a Save button.

Each Save appends the amount, as typed, to $BENCH_STATE/ledger.json.
"""

import json
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

STATE = os.environ["BENCH_STATE"]


class LedgerApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="bench.ledger")

    def do_activate(self) -> None:
        win = Gtk.ApplicationWindow(application=self, title="Bench Ledger")
        win.set_default_size(420, 180)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(24)
        label = Gtk.Label(label="_Amount", use_underline=True, xalign=0)
        amount = Gtk.Entry()
        label.set_mnemonic_widget(amount)
        status = Gtk.Label(label="", xalign=0)
        save = Gtk.Button(label="Save")

        def on_save(_b: Gtk.Button) -> None:
            path = os.path.join(STATE, "ledger.json")
            try:
                with open(path) as f:
                    rows = json.load(f)
            except FileNotFoundError:
                rows = []
            rows.append(amount.get_text())
            with open(path + ".tmp", "w") as f:
                json.dump(rows, f)
            os.replace(path + ".tmp", path)
            status.set_text("Saved")

        save.connect("clicked", on_save)
        for widget in (label, amount, save, status):
            box.append(widget)
        win.set_child(box)
        win.present()


if __name__ == "__main__":
    sys.exit(LedgerApp().run([]))
