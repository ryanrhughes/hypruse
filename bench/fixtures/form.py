"""Bench Form: a GTK 4 window with ordinary, accessible controls.

Every press of Submit appends what the form held to $BENCH_STATE/form.json,
so a check reads the outcome instead of trusting the agent's report.
"""

import json
import os
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

STATE = os.environ["BENCH_STATE"]


def append(record: dict) -> None:
    path = os.path.join(STATE, "form.json")
    try:
        with open(path) as f:
            records = json.load(f)
    except FileNotFoundError:
        records = []
    records.append(record)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(records, f)
    os.replace(tmp, path)


class FormApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="bench.form")

    def do_activate(self) -> None:
        win = Gtk.ApplicationWindow(application=self, title="Bench Form")
        win.set_default_size(520, 420)

        grid = Gtk.Grid(row_spacing=12, column_spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(grid, f"set_margin_{side}")(24)

        def labelled(row: int, text: str) -> Gtk.Entry:
            label = Gtk.Label(label=text, use_underline=True, xalign=0)
            entry = Gtk.Entry(hexpand=True)
            label.set_mnemonic_widget(entry)
            grid.attach(label, 0, row, 1, 1)
            grid.attach(entry, 1, row, 1, 1)
            return entry

        name = labelled(0, "_Full name")
        email = labelled(1, "_Email")

        subscribe = Gtk.CheckButton(label="Subscribe to the newsletter")
        grid.attach(subscribe, 1, 2, 1, 1)

        grid.attach(Gtk.Label(label="Plan", xalign=0), 0, 3, 1, 1)
        plans = Gtk.Box(spacing=12)
        free = Gtk.CheckButton(label="Free", active=True)
        pro = Gtk.CheckButton(label="Pro", group=free)
        team = Gtk.CheckButton(label="Team", group=free)
        for button in (free, pro, team):
            plans.append(button)
        grid.attach(plans, 1, 3, 1, 1)

        status = Gtk.Label(label="", xalign=0)
        submit = Gtk.Button(label="Submit")

        def on_submit(_button: Gtk.Button) -> None:
            plan = next(b.get_label() for b in (free, pro, team) if b.get_active())
            append(
                {
                    "name": name.get_text(),
                    "email": email.get_text(),
                    "subscribe": subscribe.get_active(),
                    "plan": plan,
                    "at": time.time(),
                }
            )
            status.set_text("Submitted")

        submit.connect("clicked", on_submit)
        grid.attach(submit, 1, 4, 1, 1)
        grid.attach(status, 1, 5, 1, 1)

        win.set_child(grid)
        win.present()


if __name__ == "__main__":
    sys.exit(FormApp().run([]))
