# Bench

Measures whether hypruse makes an agent better at driving an Omarchy desktop than having nothing, and whether a change to the fork helps or hurts. Every trial runs in a fresh desk (`contrib/hypruse-desk`), so it never touches your own session, starts from the same state, and can run beside other trials.

```bash
bench/run.py                                    # every task, every arm, once
bench/run.py --arm fork --task form-fill --n 5  # one cell, five times
bench/run.py --n 2 --jobs 3                     # three desks at a time
bench/report.py bench/results/<run>
```

Run it from your Hyprland session with `OMARCHY_PATH` set. It authenticates the way your own Claude Code does (`ANTHROPIC_BASE_URL` and the token in `~/.claude/settings.json`, or `ANTHROPIC_API_KEY`), and runs `claude --bare`, so no CLAUDE.md, skills, hooks or memory leak into a trial.

## Arms

| Arm | What the agent has |
|---|---|
| `bash` | Claude Code with no computer-use tools. It still has Bash, so `hyprctl`, `grim` and `wtype` are there. This is the "nothing at all" baseline, and it's stronger than it sounds |
| `upstream` | plus upstream hypruse as an MCP server (`$HYPRUSE_UPSTREAM`, default `../hypruse-upstream`, a checkout with its own `.venv`) |
| `fork` | plus this checkout's hypruse |

The prompt is the same for every arm: a short preamble saying the desktop is the session its environment points to, then the task. Set up the upstream checkout once:

```bash
git worktree add --detach ../hypruse-upstream upstream/main
(cd ../hypruse-upstream && uv sync)
```

## What a trial records

One line per trial in `results.ndjson` (each invocation also writes `run-<time>.json` with the model, arms and commits, so several runs can share a directory):

- `passed`, `detail`: the task's check, which reads the end state (window list, a fixture's output file, the filesystem, the shell's state). The agent never sees it and its own report doesn't count.
- `shortcuts`: Bash commands that match the task's ruled-out patterns, such as `mkdir` when the task said to use the Files app. The report's `pass` column counts only clean passes, and `check ok` counts every passing check.
- `wall_s`, `turns`, `tool_calls`, `tools`, `images`, `input_tokens`, `output_tokens`, `cost_usd`: from the agent's stream-json. `cost_usd` is Claude Code's list-price estimate.
- `journal`: per-tool calls, time and failures from the hypruse journal, for the MCP arms. This is where to look for what to make faster.
- `host`: windows opened on your own session during the trial, plus changes to the browser policies in `/etc` and to your theme and background. Focus events are counted too, but you may be working, so they're context, not a verdict. With `--jobs` above 1 a leak can't be pinned to one trial.

Each trial also keeps `agent.ndjson` (the full stream), `agent.err`, `mcp.json`, `journal.ndjson`, `state/` (fixture output) and, with `--keep-logs`, the desk's `hyprland.log`, under `trials/<id>/`.

## Tasks

Each task is a directory under `tasks/` with `task.json` (`prompt`, `summary`, `shortcuts` regexes, optional `timeout`), a `setup` script and a `check` script. Both scripts run with the desk's display, bus and scratch HOME, plus `BENCH_STATE` (a directory outside the desk's home for fixture output) and `BENCH_FIXTURES`. `check` exits 0 on a pass and prints one JSON line, `{"result", "detail"}`. `lib.sh` has `launch`, `wait_window`, `window_workspace` and `verdict`.

| Task | Tests |
|---|---|
| `move-window` | Window management through IPC. The bash arm has `hyprctl` too, so this is the control: a big gap here means something else is wrong |
| `form-fill` | Accessible GTK controls (`fixtures/form.py`): two text fields, a checkbox, radio buttons, a button |
| `small-targets` | Pixel precision with no accessibility tree (`fixtures/targets.py`): 14 px squares painted on a canvas, clicked in order; misses are recorded |
| `files-folder` | A real app (Nautilus), through its UI; `mkdir` is a shortcut |
| `background-picker` | Omarchy's own UI: the menu and the background picker; `omarchy-theme-bg-*` is a shortcut |

Before trusting a new task, check it both ways: run its setup and check in a desk without an agent (the check must fail), then do the task by hand and check again (it must pass).

## Reading results

Model variance is large. One run per cell shows whether things work at all; comparing arms needs at least five per cell. Report how many tasks pass every time, not only the average: an agent that gets a task right three times in five isn't one you can leave alone with it. Time trials with `--jobs 1`, since parallel desks share the CPU and GPU.
