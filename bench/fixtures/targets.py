"""Bench Targets: small numbered squares painted on a canvas.

Nothing here is in the accessibility tree, so the only way to hit a square
is to see it and click it. Every press lands in $BENCH_STATE/clicks.json
with the square it hit, or none, and a hit square turns green.
"""

import json
import os
import random
import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

STATE = os.environ["BENCH_STATE"]
SIZE = 14
COUNT = 24


def layout() -> list[tuple[int, int, int]]:
    """The same 24 positions every run, spread so no two squares or labels touch."""
    rng = random.Random(7)
    squares: list[tuple[int, int, int]] = []
    while len(squares) < COUNT:
        x, y = rng.randint(40, 840), rng.randint(40, 540)
        if all(abs(x - sx) > 70 or abs(y - sy) > 40 for _, sx, sy in squares):
            squares.append((len(squares) + 1, x, y))
    return squares


SQUARES = layout()


class TargetsApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="bench.targets")
        self.hit: set[int] = set()
        self.clicks: list[dict] = []

    def record(self, x: float, y: float) -> None:
        number = next(
            (n for n, sx, sy in SQUARES if sx <= x < sx + SIZE and sy <= y < sy + SIZE),
            None,
        )
        if number is not None:
            self.hit.add(number)
        self.clicks.append({"x": round(x, 1), "y": round(y, 1), "hit": number})
        path = os.path.join(STATE, "clicks.json")
        with open(path + ".tmp", "w") as f:
            json.dump(self.clicks, f)
        os.replace(path + ".tmp", path)

    def draw(self, _area: Gtk.DrawingArea, cr, _width: int, _height: int) -> None:
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        cr.select_font_face("Sans")
        cr.set_font_size(13)
        for number, x, y in SQUARES:
            if number in self.hit:
                cr.set_source_rgb(0.2, 0.7, 0.3)
            else:
                cr.set_source_rgb(0.55, 0.55, 0.55)
            cr.rectangle(x, y, SIZE, SIZE)
            cr.fill()
            cr.set_source_rgb(0, 0, 0)
            cr.move_to(x + SIZE + 5, y + SIZE - 2)
            cr.show_text(str(number))

    def do_activate(self) -> None:
        win = Gtk.ApplicationWindow(application=self, title="Bench Targets")
        win.set_default_size(920, 620)
        area = Gtk.DrawingArea(content_width=900, content_height=600)
        area.set_draw_func(self.draw)
        click = Gtk.GestureClick()

        def pressed(_gesture: Gtk.GestureClick, _n: int, x: float, y: float) -> None:
            self.record(x, y)
            area.queue_draw()

        click.connect("pressed", pressed)
        area.add_controller(click)
        win.set_child(area)
        win.present()


if __name__ == "__main__":
    sys.exit(TargetsApp().run([]))
