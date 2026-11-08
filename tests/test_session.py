import os
import time

from hypruse import session


def make_instance(runtime, sig, age=0.0):
    d = runtime / "hypr" / sig
    d.mkdir(parents=True)
    (d / ".socket.sock").touch()
    ts = time.time() - age
    os.utime(d, (ts, ts))
    return d


def test_discovers_missing_vars(tmp_path, monkeypatch):
    make_instance(tmp_path, "abc123_1_2")
    (tmp_path / "wayland-1").touch()
    (tmp_path / "wayland-1.lock").touch()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    session.ensure_session_env()

    assert os.environ["HYPRLAND_INSTANCE_SIGNATURE"] == "abc123_1_2"
    assert os.environ["WAYLAND_DISPLAY"] == "wayland-1"


def test_prefers_newest_live_instance_and_ignores_dead(tmp_path, monkeypatch):
    make_instance(tmp_path, "old_sig", age=500)
    make_instance(tmp_path, "new_sig", age=5)
    dead = tmp_path / "hypr" / "dead_sig"
    dead.mkdir(parents=True)  # no .socket.sock → not a live instance
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)

    session.ensure_session_env()

    assert os.environ["HYPRLAND_INSTANCE_SIGNATURE"] == "new_sig"


def test_never_overrides_existing_env(tmp_path, monkeypatch):
    make_instance(tmp_path, "discovered")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "explicit")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-7")

    session.ensure_session_env()

    assert os.environ["HYPRLAND_INSTANCE_SIGNATURE"] == "explicit"
    assert os.environ["WAYLAND_DISPLAY"] == "wayland-7"


def test_graceful_when_nothing_to_discover(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    session.ensure_session_env()  # must not raise

    assert "HYPRLAND_INSTANCE_SIGNATURE" not in os.environ
    assert "WAYLAND_DISPLAY" not in os.environ


def lock(instance, pid, socket):
    (instance / "hyprland.lock").write_text(f"{pid}\n{socket}\n")


def clear(monkeypatch, runtime):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)


def test_a_newer_nested_compositor_does_not_win_and_the_pair_matches(tmp_path, monkeypatch):
    # a desk started after login is the newest instance; picking it, or
    # pairing its signature with the host's display, reads one desktop and
    # clicks another
    host = make_instance(tmp_path, "host_sig", age=500)
    desk = make_instance(tmp_path, "desk_sig", age=5)
    lock(host, os.getpid(), "wayland-1")
    lock(desk, os.getppid(), "wayland-2")
    for name in ("wayland-1", "wayland-2"):
        (tmp_path / name).touch()
    monkeypatch.setattr(session, "_nested", lambda pid: pid == os.getppid())
    clear(monkeypatch, tmp_path)

    session.ensure_session_env()

    assert os.environ["HYPRLAND_INSTANCE_SIGNATURE"] == "host_sig"
    assert os.environ["WAYLAND_DISPLAY"] == "wayland-1"


def test_a_known_desk_is_skipped_even_when_it_looks_top_level(tmp_path, monkeypatch):
    host = make_instance(tmp_path, "host_sig", age=500)
    desk = make_instance(tmp_path, "desk_sig", age=5)
    lock(host, os.getpid(), "wayland-1")
    lock(desk, os.getpid(), "wayland-2")
    desk_dir = tmp_path / "hypruse" / "desks" / "d1"
    desk_dir.mkdir(parents=True)
    (desk_dir / "env").write_text(
        "HYPRLAND_INSTANCE_SIGNATURE=desk_sig\nWAYLAND_DISPLAY=wayland-2\n"
    )
    monkeypatch.setattr(session, "_nested", lambda pid: False)
    clear(monkeypatch, tmp_path)

    session.ensure_session_env()

    assert os.environ["HYPRLAND_INSTANCE_SIGNATURE"] == "host_sig"
    assert os.environ["WAYLAND_DISPLAY"] == "wayland-1"


def test_a_set_display_picks_the_instance_serving_it(tmp_path, monkeypatch):
    host = make_instance(tmp_path, "host_sig", age=500)
    desk = make_instance(tmp_path, "desk_sig", age=5)
    lock(host, os.getpid(), "wayland-1")
    lock(desk, os.getpid(), "wayland-2")
    monkeypatch.setattr(session, "_nested", lambda pid: False)
    clear(monkeypatch, tmp_path)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")

    session.ensure_session_env()

    assert os.environ["HYPRLAND_INSTANCE_SIGNATURE"] == "host_sig"


def test_a_set_signature_takes_its_own_display(tmp_path, monkeypatch):
    desk = make_instance(tmp_path, "desk_sig")
    lock(desk, os.getpid(), "wayland-2")
    (tmp_path / "wayland-1").touch()
    clear(monkeypatch, tmp_path)
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "desk_sig")

    session.ensure_session_env()

    assert os.environ["WAYLAND_DISPLAY"] == "wayland-2"


def test_an_instance_whose_compositor_exited_is_ignored(tmp_path, monkeypatch):
    import subprocess
    import sys

    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    live = make_instance(tmp_path, "live_sig", age=500)
    stale = make_instance(tmp_path, "stale_sig", age=5)  # socket file left behind
    lock(live, os.getpid(), "wayland-1")
    lock(stale, proc.pid, "wayland-2")
    monkeypatch.setattr(session, "_nested", lambda pid: False)
    clear(monkeypatch, tmp_path)

    session.ensure_session_env()

    assert os.environ["HYPRLAND_INSTANCE_SIGNATURE"] == "live_sig"
