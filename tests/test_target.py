"""Target switching: which desktop the tools drive (here or a desk)."""

import os
import subprocess
import sys

import pytest

from hypruse import hyprctl, target, trust
from hypruse import input as hinput

HOST = {
    "HYPRLAND_INSTANCE_SIGNATURE": "host_sig",
    "WAYLAND_DISPLAY": "wayland-1",
    "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
}


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """A fresh runtime dir, the host session env, and target state reset.
    Every variable target.use writes is set through monkeypatch first, so
    teardown puts the real values back."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    for key in target.KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in HOST.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("HYPRUSE_TARGET", raising=False)
    monkeypatch.setattr(target, "_here", None)
    monkeypatch.setattr(target, "_current", target.HERE)
    monkeypatch.setattr(target, "_owned", {})
    monkeypatch.setattr(trust, "_owned", set())
    dropped = []
    monkeypatch.setattr(hinput, "drop_devices", lambda: dropped.append(True))
    monkeypatch.setattr(trust, "remember_seat", lambda: None)
    monkeypatch.setattr(hyprctl, "forget_provider", lambda: None)
    return tmp_path, dropped


def make_desk(root, name, *, pid=None, extra=""):
    desk = root / "hypruse" / "desks" / name
    desk.mkdir(parents=True)
    (desk / "env").write_text(
        f"HYPRLAND_INSTANCE_SIGNATURE={name}_sig\n"
        "WAYLAND_DISPLAY=wayland-9\n"
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={desk}/bus\n"
        "HYPRUSE_BACKGROUND=0\n" + extra
    )
    (desk / "info").write_text("profile=omarchy\n")
    (desk / "hyprland.pid").write_text(str(pid if pid is not None else os.getpid()))
    return desk


def dead_pid():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_switching_to_a_desk_and_back_restores_the_host_env(runtime):
    root, dropped = runtime
    make_desk(root, "d1")

    result = target.use("d1")
    assert result["target"] == "d1"
    assert os.environ["HYPRLAND_INSTANCE_SIGNATURE"] == "d1_sig"
    assert os.environ["WAYLAND_DISPLAY"] == "wayland-9"
    assert os.environ["HYPRUSE_BACKGROUND"] == "0"

    target.use(target.HERE)
    assert target.current() == target.HERE
    for key, value in HOST.items():
        assert os.environ[key] == value
    # the host never had HYPRUSE_BACKGROUND set, so it must be gone again,
    # not left at the desk's 0 (which would turn background mode off here)
    assert "HYPRUSE_BACKGROUND" not in os.environ
    assert len(dropped) == 2


def test_a_desk_env_file_cannot_switch_off_a_guard(runtime, monkeypatch):
    root, _ = runtime
    monkeypatch.delenv("HYPRUSE_AUTH_GUARD", raising=False)
    make_desk(root, "d1", extra="HYPRUSE_AUTH_GUARD=0\nHYPRUSE_CONFINE=\n")

    target.use("d1")
    assert "HYPRUSE_AUTH_GUARD" not in os.environ


def test_a_stale_desk_is_refused_and_the_target_stays(runtime):
    root, dropped = runtime
    make_desk(root, "gone", pid=dead_pid())

    with pytest.raises(target.TargetError, match="not running"):
        target.use("gone")
    assert target.current() == target.HERE
    assert os.environ["HYPRLAND_INSTANCE_SIGNATURE"] == "host_sig"
    assert dropped == []


def test_an_unknown_desk_names_the_ones_that_exist(runtime):
    root, _ = runtime
    make_desk(root, "d1")
    with pytest.raises(target.TargetError, match="desks: d1"):
        target.use("nope")


@pytest.mark.parametrize("name", ["../etc", ".hidden", ""])
def test_desk_names_cannot_leave_the_desks_directory(runtime, name):
    with pytest.raises(target.TargetError):
        target.use(name)


def test_launched_windows_stay_with_their_own_compositor(runtime):
    root, _ = runtime
    make_desk(root, "d1")
    trust.note_launched("0xhost")

    target.use("d1")
    assert trust.owned() == set()
    trust.note_launched("0xdesk")

    target.use(target.HERE)
    assert trust.owned() == {"0xhost"}
    target.use("d1")
    assert trust.owned() == {"0xdesk"}


def test_a_named_target_that_is_not_running_never_falls_back_to_here(runtime, monkeypatch):
    monkeypatch.setenv("HYPRUSE_TARGET", "missing")
    with pytest.raises(target.TargetError):
        target.from_env()
    assert target.current() == target.HERE


def test_desks_lists_running_and_stale(runtime):
    root, _ = runtime
    make_desk(root, "a")
    make_desk(root, "b", pid=dead_pid())
    assert [(d["name"], d["running"]) for d in target.desks()] == [("a", True), ("b", False)]
