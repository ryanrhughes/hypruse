"""Which desktop the tools drive.

`here` is the session hypruse started in: the human's own desktop, one
seat shared with them. A desk is a nested Hyprland with a seat of its own
(its own cursor, focus and clipboard), started by `contrib/hypruse-desk`,
which leaves the variables a driver needs in
$XDG_RUNTIME_DIR/hypruse/desks/<name>/env. docs/desks.md has the why.

Everything that reaches the compositor reads the session from the process
environment at call time: hyprctl, grim and wtype inherit it, the wire
client reads WAYLAND_DISPLAY when it connects, and busctl --user follows
DBUS_SESSION_BUS_ADDRESS. So switching is swapping those variables and
dropping what was cached against the old compositor: the virtual pointer
and keyboard, the config-manager probe, the strict-mode seat baseline,
and the set of windows hypruse launched (kept per target, since window
addresses only mean something on the compositor that issued them).

Callers hold the server's tool lock, so no other tool runs mid-switch.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from hypruse import hyprctl, trust
from hypruse import input as hinput

HERE = "here"

# What a desk's env file may set. Anything else in the file is ignored, so a
# desk can't use it to turn off a guard (HYPRUSE_AUTH_GUARD, HYPRUSE_CONFINE).
KEYS = (
    "HYPRLAND_INSTANCE_SIGNATURE",
    "WAYLAND_DISPLAY",
    "DBUS_SESSION_BUS_ADDRESS",
    "HYPRUSE_BACKGROUND",
)


class TargetError(Exception):
    """No such desk, or it isn't running."""


_here: dict[str, str | None] | None = None
_current = HERE
_owned: dict[str, set[str]] = {}


def desks_root() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "hypruse" / "desks"


def _read_kv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text()
    except OSError:
        return values
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip():
            values[key.strip()] = value.strip()
    return values


def _alive(desk: Path) -> bool:
    try:
        pid = int((desk / "hyprland.pid").read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def desks() -> list[dict[str, Any]]:
    """Every desk the launcher left a directory for, running or stale."""
    root = desks_root()
    if not root.is_dir():
        return []
    found = []
    for desk in sorted(p for p in root.iterdir() if p.is_dir()):
        env = _read_kv(desk / "env")
        info = _read_kv(desk / "info")
        found.append({
            "name": desk.name,
            "running": bool(env) and _alive(desk),
            "profile": info.get("profile", ""),
            "display": env.get("WAYLAND_DISPLAY", ""),
        })
    return found


def desk_env(name: str) -> dict[str, str]:
    """The variables that reach a running desk. Raises TargetError."""
    if not name or "/" in name or name.startswith("."):
        raise TargetError(f"not a desk name: {name!r}")
    desk = desks_root() / name
    if not desk.is_dir():
        known = ", ".join(d["name"] for d in desks()) or "none"
        raise TargetError(
            f"no desk {name!r} (desks: {known}); start one with hypruse-desk start {name}"
        )
    if not _alive(desk):
        raise TargetError(f"desk {name!r} is not running; start it with hypruse-desk start {name}")
    env = {k: v for k, v in _read_kv(desk / "env").items() if k in KEYS}
    missing = [k for k in ("HYPRLAND_INSTANCE_SIGNATURE", "WAYLAND_DISPLAY") if not env.get(k)]
    if missing:
        raise TargetError(f"desk {name!r} env file lacks {', '.join(missing)}")
    return env


def current() -> str:
    return _current


def _remember_here() -> None:
    global _here
    if _here is None:
        _here = {k: os.environ.get(k) for k in KEYS}


def _apply(env: dict[str, str | None]) -> None:
    for key in KEYS:
        value = env.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def use(name: str) -> dict[str, Any]:
    """Point every tool at `name` (HERE or a running desk). Returns the
    new target's description. Raises TargetError, leaving the current
    target in place."""
    global _current
    name = (name or "").strip()
    if name == HERE:
        _remember_here()
        env: dict[str, str | None] = dict(_here or {})
    else:
        env = dict(desk_env(name))  # raises before anything changes
        _remember_here()

    if name != _current:
        hinput.drop_devices()
        _owned[_current] = trust.owned()
        _apply(env)
        _current = name
        trust.adopt_owned(_owned.get(name, set()))
        hyprctl.forget_provider()
        trust.forget_seat()
        trust.remember_seat()
    return describe()


def from_env() -> None:
    """Start on the target HYPRUSE_TARGET names (a desk name, or `here`,
    the default). A named desk that isn't running raises TargetError
    rather than falling back to `here`: an agent told it's in a desk must
    never quietly be driving the human's own desktop."""
    name = os.environ.get("HYPRUSE_TARGET", "").strip()
    if name and name != HERE:
        use(name)


def describe() -> dict[str, Any]:
    if _current == HERE:
        what = (
            "the human's own desktop: one seat shared with them, so acting in "
            "the foreground moves their cursor and focus"
        )
    else:
        what = (
            "a desk: a nested Hyprland with its own cursor, focus and clipboard; "
            "nothing here touches the human's windows, but audio, network and "
            "power are still the real machine"
        )
    return {
        "target": _current,
        "display": os.environ.get("WAYLAND_DISPLAY", ""),
        "what": what,
    }
