#!/usr/bin/env python3
"""Run computer-use tasks in fresh desks and record how each arm did.

Each trial gets its own Omarchy desk (contrib/hypruse-desk), a task's
setup script, one headless Claude Code run, and the task's check script.
The agent never sees the check. Everything the agent runs, and the hypruse
MCP server when the arm has one, is pointed at the desk: its display, its
private bus, its scratch HOME and its PATH guards.

Arms:
  bash      Claude Code with no computer-use tools (it still has Bash, so
            hyprctl, grim and wtype are all there)
  upstream  plus upstream hypruse as an MCP server ($HYPRUSE_UPSTREAM, a
            checkout with its own .venv; default ../hypruse-upstream)
  fork      plus this checkout's hypruse
  fork-a11y fork, with the desk's accessibility bus marked enabled so Qt
            apps expose their controls

    bench/run.py --arm bash --arm fork --task move-window --n 3

Results append to bench/results/<run>/results.ndjson, one line per trial;
bench/report.py turns them into a table. Each trial keeps its agent
stream, stderr, the hypruse journal and the desk's Hyprland log under
trials/<id>/.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parent
DESK = ROOT / "contrib" / "hypruse-desk"
RUNTIME = Path(os.environ["XDG_RUNTIME_DIR"])
DESK_RUN = RUNTIME / "hypruse" / "desks"
SERVERS = {
    "fork": ROOT / ".venv" / "bin" / "hypruse",
    "upstream": Path(os.environ.get("HYPRUSE_UPSTREAM", ROOT.parent / "hypruse-upstream"))
    / ".venv"
    / "bin"
    / "hypruse",
}
SERVERS["fork-image"] = SERVERS["fork"]
SERVERS["fork-a11y"] = SERVERS["fork"]
ARMS = ("bash", "upstream", "fork", "fork-image", "fork-a11y")
DEFAULT_ARMS = ("bash", "upstream", "fork")
# Variants: the same server with different settings, to test one change.
ARM_ENV = {
    # Inline image blocks instead of a file path the agent must Read. The
    # path default dates from a Claude Code that showed inline MCP images
    # to the model as base64 text.
    "fork-image": {"HYPRUSE_SCREENSHOT_MODE": "image"},
}
# Variants that change the desk rather than the server. "a11y" marks the
# desk's accessibility bus enabled, as a screen reader does, which Qt waits
# for before it exposes any app's controls (docs/desks.md).
ARM_DESK = {"fork-a11y": {"a11y"}}
MISE_DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "mise"
CLAUDE = (
    subprocess.run(["mise", "which", "claude"], capture_output=True, text=True).stdout.strip()
    or "claude"
)

PREAMBLE = (
    "You are operating a Linux desktop: Hyprland running Omarchy. It is the "
    "session your environment already points to (WAYLAND_DISPLAY and "
    "HYPRLAND_INSTANCE_SIGNATURE are set), and nobody else is using it. "
    "Finish the task below, then reply with DONE and one line on what you "
    "did, or FAILED and why.\n\nTask: "
)

# Files on the host a desk must never change: the browser policies a theme
# switch once rewrote through sudo, and the host's own theme.
WATCHED_FILES = [
    Path("/etc/brave/policies/managed/color.json"),
    Path("/etc/chromium/policies/managed/color.json"),
    Path.home() / ".local/state/omarchy/current/theme.name",
    Path.home() / ".local/state/omarchy/current/background",
]

# Every trial's state directory sits under bench/results/<run>/trials/, and
# fixtures carry its path in BENCH_STATE: agents have found it through another
# process's /proc/<pid>/environ.
CHEATS = [r"BENCH_STATE", r"/trials/[^\s\"']*/state"]

_desk_start_lock = threading.Lock()
_results_lock = threading.Lock()


# --- tasks ------------------------------------------------------------------


class Task:
    def __init__(self, path: Path) -> None:
        self.name = path.name
        self.dir = path
        spec = json.loads((path / "task.json").read_text())
        self.prompt = spec["prompt"]
        self.summary = spec.get("summary", "")
        self.shortcuts = [re.compile(p) for p in spec.get("shortcuts", [])]
        # Reading the bench's own state (a fixture's output, the expected
        # answer) fails a trial of either kind: it's the answer key, not a route.
        self.cheats = [re.compile(p) for p in [*CHEATS, *spec.get("cheats", [])]]
        self.timeout = spec.get("timeout", 480)
        # Settings for the hypruse server in the MCP arms, e.g. background mode.
        self.server_env = spec.get("server_env", {})
        # "gui": the task is about operating the interface, so a shortcut the
        # task rules out fails the trial. "result": any route to the outcome
        # counts, as in OSWorld; shortcuts are recorded but don't fail it.
        self.kind = spec.get("kind", "gui")
        self.setup_timeout = spec.get("setup_timeout", 60)


def load_tasks(names: list[str]) -> list[Task]:
    available = {
        p.name: p for p in sorted((BENCH / "tasks").iterdir()) if (p / "task.json").exists()
    }
    if not names:
        # a task marked "disabled" (with the reason) runs only when named
        return [
            Task(p)
            for p in available.values()
            if "disabled" not in json.loads((p / "task.json").read_text())
        ]
    missing = [n for n in names if n not in available]
    if missing:
        sys.exit(f"unknown task(s): {', '.join(missing)}; have {', '.join(available)}")
    return [Task(available[n]) for n in names]


# --- desks ------------------------------------------------------------------


def read_kv(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        key, _, value = line.partition("=")
        if key:
            out[key] = value
    return out


class Desk:
    """One fresh Omarchy desk for one trial."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.run = DESK_RUN / name

    def start(self) -> None:
        # The desk script finds its new compositor by diffing the instance
        # list, so two starts at once could each claim the other's.
        # One retry: a nested output now and then fails to get its first
        # buffers, and the desk script says so instead of starting blind.
        for attempt in (0, 1):
            with _desk_start_lock:
                started = subprocess.run(
                    [str(DESK), "start", self.name, "--fresh"],
                    capture_output=True,
                    text=True,
                )
            if started.returncode == 0:
                break
            if attempt:
                started.check_returncode()
        self.display = {
            k: v
            for k, v in read_kv(self.run / "env").items()
            if k
            in (
                "HYPRLAND_INSTANCE_SIGNATURE",
                "WAYLAND_DISPLAY",
                "DBUS_SESSION_BUS_ADDRESS",
                "HYPRUSE_BACKGROUND",
                "TMUX_TMPDIR",
            )
        }
        self.home = read_kv(self.run / "info")["home"]
        self.env = self._env()
        self._wait_for_shell()

    def _env(self) -> dict[str, str]:
        home = self.home
        env = {
            "PATH": f"{self.run / 'bin'}:{os.environ['PATH']}",
            "HOME": home,
            "USER": os.environ.get("USER", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "TERM": "xterm-256color",
            "XDG_RUNTIME_DIR": str(RUNTIME),
            "XDG_CONFIG_HOME": f"{home}/.config",
            "XDG_STATE_HOME": f"{home}/.local/state",
            "XDG_DATA_HOME": f"{home}/.local/share",
            "XDG_CACHE_HOME": f"{home}/.cache",
            "XDG_SESSION_TYPE": "wayland",
            "XDG_CURRENT_DESKTOP": "Hyprland",
            "OMARCHY_PATH": os.environ["OMARCHY_PATH"],
            # mise keeps its installs under XDG_DATA_HOME, so with the
            # desk's scratch one every mise-managed tool (claude included)
            # was downloaded again for each trial.
            "MISE_DATA_DIR": str(MISE_DATA),
        }
        env.update(self.display)
        return env

    def _wait_for_shell(self) -> None:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            ok = subprocess.run(
                ["omarchy-shell", "shell", "ping"],
                env=self.env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if ok.returncode == 0 and self._a11y_ready():
                time.sleep(1.5)  # let the bar and wallpaper settle
                return
            time.sleep(0.5)
        raise RuntimeError(
            f"desk {self.name}: the shell or the accessibility registry never came up"
        )

    def _a11y_ready(self) -> bool:
        """Apps register with the accessibility registry when they start, so
        one launched before the desk's registry is up has no tree at all."""
        got = subprocess.run(
            [
                "busctl",
                "--user",
                "call",
                "org.a11y.Bus",
                "/org/a11y/bus",
                "org.a11y.Bus",
                "GetAddress",
            ],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        address = got.stdout.strip().removeprefix("s ").strip('"')
        if got.returncode != 0 or not address:
            return False
        names = subprocess.run(
            ["busctl", f"--address={address}", "list", "--no-legend"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return "org.a11y.atspi.Registry" in names.stdout

    def enable_a11y(self) -> None:
        subprocess.run(
            [
                "busctl",
                "--user",
                "set-property",
                "org.a11y.Bus",
                "/org/a11y/bus",
                "org.a11y.Status",
                "IsEnabled",
                "b",
                "true",
            ],
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def stop(self, keep_log: Path | None) -> None:
        log = self.run / "hyprland.log"
        if keep_log and log.exists():
            keep_log.write_bytes(log.read_bytes())
        subprocess.run([str(DESK), "stop", self.name, "--purge"], capture_output=True, text=True)


# --- the host -----------------------------------------------------------------


class HostWatch(threading.Thread):
    """Record what happens on the human's own session while a trial runs.

    Window opens are the strong signal: nothing in a trial should open a
    window on the host. Focus and workspace changes are recorded too, but
    the human may be working, so they are context rather than a verdict.
    """

    EVENTS = ("openwindow", "activewindowv2", "workspacev2", "focusedmonv2")

    def __init__(self, signature: str) -> None:
        super().__init__(daemon=True)
        self.path = RUNTIME / "hypr" / signature / ".socket2.sock"
        self.events: list[tuple[float, str, str]] = []
        self._stop = threading.Event()
        self.files_before = self._files()

    @staticmethod
    def _files() -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for path in WATCHED_FILES:
            try:
                stat = path.lstat()
                target = os.readlink(path) if path.is_symlink() else path.read_text()[:200]
                out[str(path)] = f"{stat.st_mtime_ns}:{target}"
            except OSError:
                out[str(path)] = None
        return out

    def run(self) -> None:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.connect(str(self.path))
            sock.settimeout(0.5)
            buf = b""
            while not self._stop.is_set():
                try:
                    chunk = sock.recv(65536)
                except TimeoutError:
                    continue
                if not chunk:
                    return
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for line in lines:
                    event, _, data = line.decode(errors="replace").partition(">>")
                    if event in self.EVENTS:
                        self.events.append((time.time(), event, data))

    def finish(self) -> dict:
        self._stop.set()
        self.join(timeout=2)
        after = self._files()
        opened = []
        for _, event, data in self.events:
            if event == "openwindow":
                _addr, _ws, cls, title = (data.split(",", 3) + ["", "", "", ""])[:4]
                if cls != "aquamarine":  # the desk's own window
                    opened.append(f"{cls}: {title}")
        return {
            "windows_opened": opened,
            "focus_events": sum(1 for _, e, _ in self.events if e != "openwindow"),
            "files_changed": [p for p in after if after[p] != self.files_before[p]],
        }


# --- the agent ----------------------------------------------------------------


def credentials() -> dict[str, str]:
    """The gateway and key the human's own Claude Code uses, so a bare run
    authenticates the same way without reading their HOME."""
    env = {}
    try:
        settings = json.loads((Path.home() / ".claude" / "settings.json").read_text()).get(
            "env", {}
        )
    except (OSError, ValueError):
        settings = {}
    base = os.environ.get("ANTHROPIC_BASE_URL") or settings.get("ANTHROPIC_BASE_URL")
    key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or settings.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )
    if base:
        env["ANTHROPIC_BASE_URL"] = base
    if not key:
        sys.exit("no Anthropic key: set ANTHROPIC_API_KEY")
    env["ANTHROPIC_API_KEY"] = key
    return env


def mcp_config(arm: str, task: Task, desk: Desk, trial_dir: Path) -> Path | None:
    if arm == "bash":
        return None
    server = SERVERS[arm]
    if not server.exists():
        sys.exit(f"{arm}: no hypruse at {server}")
    env = dict(desk.display)
    env["HYPRUSE_JOURNAL"] = str(trial_dir / "journal.ndjson")
    env.update(task.server_env)
    env.update(ARM_ENV.get(arm, {}))
    config = {
        "mcpServers": {"hypruse": {"type": "stdio", "command": str(server), "args": [], "env": env}}
    }
    path = trial_dir / "mcp.json"
    path.write_text(json.dumps(config, indent=2))
    return path


def run_agent(
    task: Task, arm: str, model: str, desk: Desk, trial_dir: Path, creds: dict[str, str]
) -> tuple[bool, float]:
    cmd = [
        CLAUDE,
        "--bare",
        "-p",
        "--model",
        model,
        "--no-session-persistence",
        "--output-format",
        "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
        "--strict-mcp-config",
    ]
    config = mcp_config(arm, task, desk, trial_dir)
    if config:
        # The flag takes several values, so a prompt after it would be
        # read as one more config file; the prompt goes in on stdin.
        cmd += [f"--mcp-config={config}"]

    env = dict(desk.env)
    env.update(creds)
    env.update({"MCP_TIMEOUT": "30000", "MCP_TOOL_TIMEOUT": "120000", "API_TIMEOUT_MS": "600000"})

    started = time.monotonic()
    with open(trial_dir / "agent.ndjson", "w") as out, open(trial_dir / "agent.err", "w") as err:
        proc = subprocess.Popen(
            cmd,
            cwd=desk.home,
            env=env,
            stdout=out,
            stderr=err,
            stdin=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        proc.stdin.write(PREAMBLE + task.prompt)
        proc.stdin.close()
        try:
            proc.wait(timeout=task.timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            timed_out = True
    return timed_out, time.monotonic() - started


def short_tool(name: str) -> str:
    return name.removeprefix("mcp__hypruse__")


def parse_stream(path: Path, task: Task) -> dict:
    tools: collections.Counter[str] = collections.Counter()
    images = 0
    calls: list[str] = []
    result: dict = {}
    final = ""
    for line in path.read_text(errors="replace").splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        kind = obj.get("type")
        if kind == "assistant":
            for block in obj.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    tools[short_tool(block["name"])] += 1
                    # "Bash {...}", "hypr {...}": a task's shortcut patterns
                    # can rule out a shell command or a tool call alike
                    args = json.dumps(block.get("input", {}))
                    calls.append(f"{short_tool(block['name'])} {args}")
                elif block.get("type") == "text":
                    final = block.get("text", "")
        elif kind == "user":
            content = obj.get("message", {}).get("content", [])
            for block in content if isinstance(content, list) else []:
                if block.get("type") == "tool_result" and isinstance(block.get("content"), list):
                    images += sum(1 for c in block["content"] if c.get("type") == "image")
        elif kind == "result":
            result = obj
    usage = result.get("usage", {})
    shortcuts = [call for call in calls if any(p.search(call) for p in task.shortcuts)]
    cheats = [call for call in calls if any(p.search(call) for p in task.cheats)]
    return {
        "turns": result.get("num_turns"),
        "agent_ms": result.get("duration_ms"),
        "cost_usd": result.get("total_cost_usd"),
        "input_tokens": (
            usage.get("input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
        ),
        "output_tokens": usage.get("output_tokens", 0),
        "tool_calls": sum(tools.values()),
        "tools": dict(tools),
        "images": images,
        "shortcuts": shortcuts,
        "cheats": cheats,
        "agent_said": final.strip().splitlines()[0][:200] if final.strip() else "",
        "agent_error": result.get("subtype") if result.get("is_error") else None,
    }


def journal_summary(path: Path) -> dict:
    """Per-tool time and failures from the hypruse journal, when there is one."""
    if not path.exists():
        return {}
    by_tool: dict[str, dict] = {}
    for line in path.read_text().splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if "tool" not in entry or entry.get("parent") is not None:
            continue
        slot = by_tool.setdefault(entry["tool"], {"calls": 0, "ms": 0.0, "failed": 0})
        slot["calls"] += 1
        slot["ms"] += entry.get("ms", 0)
        if entry.get("outcome") != "ok":
            slot["failed"] += 1
    for slot in by_tool.values():
        slot["ms"] = round(slot["ms"])
    return by_tool


# --- trials -------------------------------------------------------------------


def trial(
    task: Task,
    arm: str,
    rep: int,
    args: argparse.Namespace,
    out: Path,
    creds: dict[str, str],
    host_signature: str,
) -> dict:
    trial_id = f"{task.name}.{arm}.{rep}.{uuid.uuid4().hex[:6]}"
    trial_dir = out / "trials" / trial_id
    state = trial_dir / "state"
    state.mkdir(parents=True)
    desk = Desk(f"bench-{uuid.uuid4().hex[:8]}")
    record: dict = {
        "trial": trial_id,
        "task": task.name,
        "arm": arm,
        "rep": rep,
        "model": args.model,
        "kind": task.kind,
        "started": time.time(),
    }
    try:
        desk.start()
        if "a11y" in ARM_DESK.get(arm, ()):
            desk.enable_a11y()
        task_env = dict(
            desk.env,
            BENCH_STATE=str(state),
            BENCH_FIXTURES=str(BENCH / "fixtures"),
            BENCH_HYPRUSE=str(SERVERS["fork"]),
        )
        subprocess.run(
            [str(task.dir / "setup")],
            env=task_env,
            check=True,
            timeout=task.setup_timeout,
            capture_output=True,
            text=True,
        )

        watch = HostWatch(host_signature)
        watch.start()
        timed_out, wall = run_agent(task, arm, args.model, desk, trial_dir, creds)
        record["host"] = watch.finish()

        check = subprocess.run(
            [str(task.dir / "check")], env=task_env, capture_output=True, text=True, timeout=30
        )
        try:
            verdict = json.loads(check.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            verdict = {
                "result": "fail",
                "detail": f"check printed nothing ({check.stderr.strip()[:200]})",
            }
        record.update(
            {
                "passed": check.returncode == 0,
                "detail": verdict.get("detail", ""),
                # partial credit, for tasks with checkpoints: the share met
                "score": verdict.get("score", 1.0 if check.returncode == 0 else 0.0),
                "timed_out": timed_out,
                "wall_s": round(wall, 1),
            }
        )
        record.update(parse_stream(trial_dir / "agent.ndjson", task))
        record["journal"] = journal_summary(trial_dir / "journal.ndjson")
    except (subprocess.CalledProcessError, RuntimeError, subprocess.TimeoutExpired) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        record.update({"passed": False, "infra_error": str(detail).strip()[-500:]})
    finally:
        desk.stop(keep_log=trial_dir / "hyprland.log" if args.keep_logs else None)

    with _results_lock, open(out / "results.ndjson", "a") as f:
        f.write(json.dumps(record) + "\n")
    mark = "PASS" if record.get("passed") else ("INFRA" if "infra_error" in record else "FAIL")
    print(
        f"{mark:5} {task.name:18} {arm:9} rep {rep}  {record.get('wall_s', '-')}s  "
        f"turns {record.get('turns', '-')}  tools {record.get('tool_calls', '-')}  "
        f"{record.get('detail') or record.get('infra_error', '')}",
        flush=True,
    )
    return record


def rescore(out: Path) -> None:
    """Recompute every trial's shortcuts from its stored agent stream, for
    when a task's patterns were wrong. Pass/fail is the check's and stays."""
    path = out / "results.ndjson"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    tasks = {p.name: Task(p) for p in (BENCH / "tasks").iterdir() if (p / "task.json").exists()}
    changed = 0
    for row in rows:
        stream = out / "trials" / row["trial"] / "agent.ndjson"
        if "infra_error" in row or not stream.exists() or row["task"] not in tasks:
            continue
        parsed = parse_stream(stream, tasks[row["task"]])
        for key in ("shortcuts", "cheats"):
            if parsed[key] != row.get(key, []):
                changed += 1
                before = len(row.get(key) or [])
                print(f"{row['trial']}: {before} -> {len(parsed[key])} {key}")
                row[key] = parsed[key]
        row.setdefault("kind", tasks[row["task"]].kind)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"{changed} trial(s) rescored in {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--arm", action="append", choices=ARMS, help="repeatable; default bash, upstream, fork"
    )
    parser.add_argument("--task", action="append", default=[], help="repeatable; default all")
    parser.add_argument("--n", type=int, default=1, help="repeats per task and arm")
    parser.add_argument("--model", default="claude-sonnet-5-5")
    parser.add_argument(
        "--jobs", type=int, default=1, help="trials at once; above 1, timings share the machine"
    )
    parser.add_argument("--out", help="results directory (default bench/results/<timestamp>)")
    parser.add_argument("--keep-logs", action="store_true", help="keep each desk's Hyprland log")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip trials --out already has a result for (same task, arm and repeat)",
    )
    parser.add_argument(
        "--rescore",
        metavar="DIR",
        help="re-read each trial in DIR against the tasks' current shortcut patterns, then exit",
    )
    args = parser.parse_args()
    if args.rescore:
        rescore(Path(args.rescore))
        return

    host = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not host:
        sys.exit("run this from your Hyprland session: HYPRLAND_INSTANCE_SIGNATURE is not set")
    if not os.environ.get("OMARCHY_PATH"):
        sys.exit("OMARCHY_PATH is not set")

    tasks = load_tasks(args.task)
    arms = args.arm or list(DEFAULT_ARMS)
    out = (
        Path(args.out).resolve() if args.out else BENCH / "results" / time.strftime("%Y%m%d-%H%M%S")
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / f"run-{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(
        json.dumps(
            {
                "model": args.model,
                "arms": arms,
                "tasks": [t.name for t in tasks],
                "n": args.n,
                "jobs": args.jobs,
                "fork_head": _git_head(ROOT),
                "upstream_head": _git_head(SERVERS["upstream"].parents[2]),
            },
            indent=2,
        )
    )
    creds = credentials()

    # Interleave arms within each repeat so drift (load, the gateway) hits
    # every arm alike rather than whichever ran last.
    plan = [(task, arm, rep) for rep in range(1, args.n + 1) for task in tasks for arm in arms]
    if args.resume and (out / "results.ndjson").exists():
        done = {
            (r["task"], r["arm"], r["rep"])
            for r in map(json.loads, (out / "results.ndjson").read_text().splitlines())
            if "infra_error" not in r
        }
        plan = [p for p in plan if (p[0].name, p[1], p[2]) not in done]
    print(f"{len(plan)} trial(s) -> {out}", flush=True)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(lambda p: trial(*p, args, out, creds, host), plan))
    print(f"\nbench/report.py {out}")


def _git_head(path: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return None


if __name__ == "__main__":
    main()
