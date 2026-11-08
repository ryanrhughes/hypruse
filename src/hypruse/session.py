"""Session discovery for stripped environments.

Desktop apps launched via dbus/systemd activation often run their MCP
servers without the session variables a terminal has, notably
HYPRLAND_INSTANCE_SIGNATURE and WAYLAND_DISPLAY. Both are
recoverable from the filesystem, because the sockets they point at live
in deterministic places:

    $XDG_RUNTIME_DIR/hypr/<instance-signature>/.socket.sock
    $XDG_RUNTIME_DIR/hypr/<instance-signature>/hyprland.lock  (pid, then socket)
    $XDG_RUNTIME_DIR/wayland-<n>

ensure_session_env() fills any missing variable from what it finds. The
two variables must name the SAME compositor: hyprctl follows the
signature and the input devices follow the display, so a mismatched pair
reads one desktop and clicks another. When several Hyprland instances are
alive (a nested one, such as a hypruse desk, runs next to the human's),
the pair comes from one instance's lock file, and the human's session is
preferred: desks hypruse knows about are skipped, then a top-level
compositor beats a nested one, then the most recently started wins.
"""

from __future__ import annotations

import os
from pathlib import Path


def _runtime_dir() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")


def _read_lock(instance: Path) -> tuple[int | None, str | None]:
    """(pid, wayland socket) from an instance's hyprland.lock, either None
    when the file is missing or unreadable (older Hyprland, a test)."""
    try:
        lines = (instance / "hyprland.lock").read_text().split()
    except OSError:
        return None, None
    pid = int(lines[0]) if lines and lines[0].isdigit() else None
    socket = lines[1] if len(lines) > 1 else None
    return pid, socket


def _pid_alive(pid: int | None) -> bool:
    if pid is None:
        return True  # nothing to check against; the socket file has to do
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _nested(pid: int | None) -> bool:
    """True when this compositor runs inside another one. A nested Hyprland
    is a Wayland client of its parent, so it was started with the parent's
    WAYLAND_DISPLAY; a top-level one on DRM never has it."""
    if pid is None:
        return False
    try:
        env = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except OSError:
        return False
    return any(entry.startswith(b"WAYLAND_DISPLAY=") for entry in env)


def _known_desks(runtime: Path) -> set[str]:
    """Signatures of the desks contrib/hypruse-desk started (see target.py)."""
    signatures = set()
    for env_file in (runtime / "hypruse" / "desks").glob("*/env"):
        try:
            text = env_file.read_text()
        except OSError:
            continue
        for line in text.splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "HYPRLAND_INSTANCE_SIGNATURE" and value.strip():
                signatures.add(value.strip())
    return signatures


def _live_instances(runtime: Path) -> list[tuple[Path, int | None, str | None]]:
    hypr = runtime / "hypr"
    if not hypr.is_dir():
        return []
    live = []
    for d in hypr.iterdir():
        if not (d.is_dir() and (d / ".socket.sock").exists()):
            continue
        pid, socket = _read_lock(d)
        if _pid_alive(pid):
            live.append((d, pid, socket))
    return live


def _ranked(runtime: Path) -> list[tuple[Path, int | None, str | None]]:
    """Live instances, the human's own session first."""
    desks = _known_desks(runtime)
    return sorted(
        _live_instances(runtime),
        key=lambda inst: (inst[0].name in desks, _nested(inst[1]), -inst[0].stat().st_mtime),
    )


def discover_hyprland_instance(runtime: Path) -> str | None:
    ranked = _ranked(runtime)
    return ranked[0][0].name if ranked else None


def discover_wayland_display(runtime: Path) -> str | None:
    socks = [
        p.name
        for p in runtime.glob("wayland-*")
        if not p.name.endswith(".lock")
    ]
    return sorted(socks)[0] if socks else None


def ensure_session_env() -> None:
    """Fill missing session variables in-place; never overrides existing ones.
    Whatever is filled in names the same compositor as what was already set."""
    runtime = _runtime_dir()
    os.environ.setdefault("XDG_RUNTIME_DIR", str(runtime))
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    display = os.environ.get("WAYLAND_DISPLAY")
    if sig and display:
        return

    if sig:
        _, socket = _read_lock(runtime / "hypr" / sig)
        display = socket or discover_wayland_display(runtime)
    elif display:
        match = [inst for inst in _ranked(runtime) if inst[2] == display]
        sig = match[0][0].name if match else discover_hyprland_instance(runtime)
    else:
        ranked = _ranked(runtime)
        if ranked:
            instance, _, socket = ranked[0]
            sig = instance.name
            display = socket or discover_wayland_display(runtime)
        else:
            display = discover_wayland_display(runtime)

    if sig:
        os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = sig
    if display:
        os.environ["WAYLAND_DISPLAY"] = display
