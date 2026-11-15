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
| `fork-image` | `fork`, with screenshots inline instead of as a file path (about 15× the cost) |
| `fork-a11y` | `fork`, in a desk whose accessibility bus is marked enabled, the way a screen reader marks it. Qt apps (omacalc, hype, omacut, disktree) only expose their controls then; see `docs/desks.md` |

The prompt is the same for every arm: a short preamble saying the desktop is the session its environment points to, then the task. Set up the upstream checkout once:

```bash
git worktree add --detach ../hypruse-upstream upstream/main
(cd ../hypruse-upstream && uv sync)
```

## What a trial records

One line per trial in `results.ndjson` (each invocation also writes `run-<time>.json` with the model, arms and commits, so several runs can share a directory):

- `passed`, `detail`: the task's check, which reads the end state (window list, a fixture's output file, the filesystem, the shell's state). The agent never sees it and its own report doesn't count.
- `score`: the share of the task's checkpoints met, for partial credit on long tasks (1 or 0 for a task without checkpoints).
- `shortcuts`: tool calls that match the task's ruled-out patterns, such as `mkdir` when the task said to use the Files app. On a `gui` task a shortcut fails the trial; on a `result` task it's recorded but any route counts. The report's `pass` column counts clean passes, and `check ok` counts every passing check.
- `cheats`: tool calls that read the bench's own state (`BENCH_STATE`, a trial's `state/` directory), where a fixture's output or a task's expected answer lives. Agents have found it through another process's `/proc/<pid>/environ`. A cheat fails the trial whatever its kind.
- `wall_s`, `turns`, `tool_calls`, `tools`, `images`, `input_tokens`, `output_tokens`, `cost_usd`: from the agent's stream-json. `cost_usd` is Claude Code's list-price estimate.
- `journal`: per-tool calls, time and failures from the hypruse journal, for the MCP arms. This is where to look for what to make faster.
- `host`: windows opened on your own session during the trial, plus changes to the browser policies in `/etc` and to your theme and background. Focus events are counted too, but you may be working, so they're context, not a verdict. With `--jobs` above 1 a leak can't be pinned to one trial. Windows you open yourself count too: in the first Omarchy pilot, HEY, Spotify and two browser windows you opened while working showed up as leaks on every trial running at the time. Before calling one a leak, check the trial's tool calls for a launch, and the window's process: one the user's systemd started from your own session is yours.

Each trial also keeps `agent.ndjson` (the full stream), `agent.err`, `mcp.json`, `journal.ndjson`, `state/` (fixture output) and, with `--keep-logs`, the desk's `hyprland.log`, under `trials/<id>/`.

## Tasks

Each task is a directory under `tasks/` with `task.json`, a `setup` script and a `check` script. `task.json` has `prompt`, `summary`, `kind` (`gui`, the default, or `result`), `shortcuts` and `cheats` regexes, and optionally `timeout`, `setup_timeout`, `server_env` and `disabled` (with the reason; the task then runs only when named). Both scripts run with the desk's display, bus and scratch HOME, plus `BENCH_STATE` (a directory outside the desk's home for fixture output and expected answers), `BENCH_FIXTURES` and `BENCH_HYPRUSE` (this checkout's CLI, for a setup that has to type into an app). `check` exits 0 on a pass and prints one JSON line, `{"result", "detail", "score"}`. `lib.sh` has `launch`, `wait_window`, `window_workspace`, `window_address`, `focus_title` and `verdict`; Python checks use `checklib.Checkpoints`, where `add` is a scored checkpoint and `guard` is something the agent must not break (breaking one fails the trial with a score of 0).

The document fixtures under `fixtures/docs/` are checked in so every trial starts from the same bytes; `fixtures/docs/make.sh` rebuilds them from their sources.

| Task | Tests |
|---|---|
| `move-window` | Window management through IPC. The bash arm has `hyprctl` too, so this is the control: a big gap here means something else is wrong |
| `form-fill` | Accessible GTK controls (`fixtures/form.py`): two text fields, a checkbox, radio buttons, a button |
| `small-targets` | Pixel precision with no accessibility tree (`fixtures/targets.py`): 14 px squares painted on a canvas, clicked in order; misses are recorded |
| `files-folder` | A real app (Nautilus), through its UI; `mkdir` is a shortcut |
| `background-picker` | Omarchy's own UI: the menu and the background picker; `omarchy-theme-bg-*` is a shortcut |
| `beside-human` | Background mode: fill the form while a simulated person types into their own terminal (`fixtures/human.py`), without taking their focus or a keystroke |
| `wizard` | Hard GTK controls over three pages: a dropdown, a long list, a slider and a spin button (`fixtures/wizard.py`) |
| `hotkey-workspace` | Omarchy's hotkeys, pressed as keys: switch workspace and open a terminal |

### Omarchy apps

An OSWorld-style set on the apps Omarchy ships, each checked against what the app saved:

| Task | Kind | Tests |
|---|---|---|
| `omarchy-theme` | gui | The menu's theme picker |
| `omacalc-total` | result | Read a random total only the calculator shows, do arithmetic in omacalc, type the result into another window (`fixtures/ledger.py`) |
| `hype-deck` | gui | Reorder slides, change theme, add a slide and save in Hype's editor |
| `signed-contract` | gui | Place a saved signature and today's date on the right lines of a PDF in Signed, which has no accessibility tree; the check diffs the rendered page |
| `calc-revenue` | gui | LibreOffice Calc: a formula column, a sort, a frozen header row, saved as xlsx through the keep-format prompt |
| `pinta-crop` | gui | Crop to a region by eye and resize to exact pixels in Pinta |
| `files-handoff` | gui | Nautilus: bookmark a folder and compress three chosen files (with look-alikes beside them) into a named zip |
| `lazygit-hunk` | gui | A terminal UI: stage one hunk of two in lazygit and commit it |
| `invoice-report` | result | Long and across apps: read a PDF in Papers, build a sheet with formulas and a chart in Calc, write it up in Writer; eight checkpoints |

Before trusting a new task, check it both ways: run its setup and check in a desk without an agent (the check must fail), then do the task by hand and check again (it must pass).

## Reading results

Model variance is large. One run per cell shows whether things work at all; comparing arms needs at least five per cell. Report how many tasks pass every time, not only the average: an agent that gets a task right three times in five isn't one you can leave alone with it. Time trials with `--jobs 1`, since parallel desks share the CPU and GPU.
