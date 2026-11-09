"""Bench Setup: a three-page GTK 4 wizard with the controls agents find hard.

Page 1 has a dropdown, page 2 a long time-zone list that has to be
scrolled, page 3 a slider and a spin button that need exact values. Finish
writes what the wizard held to $BENCH_STATE/wizard.json; nothing is written
before that, so a wizard left half done reads as never finished.
"""

import json
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

STATE = os.environ["BENCH_STATE"]

REGIONS = [
    "Africa",
    "Antarctica",
    "Asia",
    "Caribbean",
    "Central America",
    "Europe",
    "Middle East",
    "North America",
    "Oceania",
    "South America",
]

ZONES = sorted(
    f"{area}/{city}"
    for area, cities in {
        "Africa": ["Cairo", "Lagos", "Nairobi", "Johannesburg", "Casablanca", "Accra"],
        "America": [
            "Anchorage",
            "Bogota",
            "Chicago",
            "Denver",
            "Halifax",
            "Lima",
            "Los_Angeles",
            "Mexico_City",
            "New_York",
            "Phoenix",
            "Santiago",
            "Sao_Paulo",
            "Toronto",
            "Vancouver",
            "Winnipeg",
            "Caracas",
            "Havana",
            "Panama",
        ],
        "Asia": [
            "Bangkok",
            "Dhaka",
            "Dubai",
            "Hong_Kong",
            "Jakarta",
            "Karachi",
            "Kolkata",
            "Manila",
            "Seoul",
            "Shanghai",
            "Singapore",
            "Taipei",
            "Tehran",
            "Tokyo",
        ],
        "Atlantic": ["Azores", "Reykjavik", "Bermuda", "Canary"],
        "Australia": ["Adelaide", "Brisbane", "Darwin", "Hobart", "Melbourne", "Perth", "Sydney"],
        "Europe": [
            "Amsterdam",
            "Athens",
            "Berlin",
            "Dublin",
            "Helsinki",
            "Istanbul",
            "Lisbon",
            "London",
            "Madrid",
            "Moscow",
            "Oslo",
            "Paris",
            "Prague",
            "Rome",
            "Stockholm",
            "Vienna",
            "Warsaw",
            "Zurich",
        ],
        "Pacific": ["Auckland", "Fiji", "Guam", "Honolulu", "Noumea", "Tahiti", "Tongatapu"],
    }.items()
    for city in cities
)


class WizardApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="bench.wizard")

    def do_activate(self) -> None:
        win = Gtk.ApplicationWindow(application=self, title="Bench Setup")
        win.set_default_size(560, 460)

        stack = Gtk.Stack()
        stack.set_vexpand(True)

        def page(title: str) -> Gtk.Box:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            for side in ("top", "bottom", "start", "end"):
                getattr(box, f"set_margin_{side}")(20)
            heading = Gtk.Label(label=title, xalign=0)
            heading.add_css_class("title-2")
            box.append(heading)
            return box

        # Page 1: a dropdown
        p1 = page("Step 1 of 3: Region")
        region_label = Gtk.Label(label="_Region", use_underline=True, xalign=0)
        region = Gtk.DropDown.new_from_strings(REGIONS)
        region_label.set_mnemonic_widget(region)
        p1.append(region_label)
        p1.append(region)

        # Page 2: a long list that has to be scrolled
        p2 = page("Step 2 of 3: Time zone")
        zones = Gtk.ListBox()
        zones.set_selection_mode(Gtk.SelectionMode.SINGLE)
        for zone in ZONES:
            row = Gtk.ListBoxRow()
            row.set_child(Gtk.Label(label=zone, xalign=0))
            zones.append(row)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(zones)
        p2.append(scroller)

        # Page 3: exact values on a slider and a spin button
        p3 = page("Step 3 of 3: Output")
        volume_label = Gtk.Label(label="_Volume", use_underline=True, xalign=0)
        volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        volume.set_value(25)
        volume.set_draw_value(True)
        volume.set_digits(0)
        volume_label.set_mnemonic_widget(volume)
        copies_label = Gtk.Label(label="_Copies", use_underline=True, xalign=0)
        copies = Gtk.SpinButton.new_with_range(1, 20, 1)
        copies.set_value(1)
        copies_label.set_mnemonic_widget(copies)
        for widget in (volume_label, volume, copies_label, copies):
            p3.append(widget)

        pages = [p1, p2, p3]
        for i, p in enumerate(pages):
            stack.add_named(p, str(i))

        back = Gtk.Button(label="Back")
        forward = Gtk.Button(label="Next")
        status = Gtk.Label(label="", xalign=0, hexpand=True)
        current = {"i": 0}

        def show(i: int) -> None:
            current["i"] = i
            stack.set_visible_child_name(str(i))
            back.set_sensitive(i > 0)
            forward.set_label("Finish" if i == len(pages) - 1 else "Next")

        def on_back(_b: Gtk.Button) -> None:
            show(max(0, current["i"] - 1))

        def on_forward(_b: Gtk.Button) -> None:
            if current["i"] < len(pages) - 1:
                show(current["i"] + 1)
                return
            row = zones.get_selected_row()
            copies.update()
            record = {
                "region": REGIONS[region.get_selected()],
                "timezone": row.get_child().get_label() if row else None,
                "volume": round(volume.get_value()),
                "copies": copies.get_value_as_int(),
            }
            path = os.path.join(STATE, "wizard.json")
            with open(path + ".tmp", "w") as f:
                json.dump(record, f)
            os.replace(path + ".tmp", path)
            status.set_text("Finished")

        back.connect("clicked", on_back)
        forward.connect("clicked", on_forward)

        buttons = Gtk.Box(spacing=8)
        for side in ("bottom", "start", "end"):
            getattr(buttons, f"set_margin_{side}")(16)
        buttons.append(status)
        buttons.append(back)
        buttons.append(forward)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.append(stack)
        outer.append(buttons)
        win.set_child(outer)
        show(0)
        win.present()


if __name__ == "__main__":
    sys.exit(WizardApp().run([]))
