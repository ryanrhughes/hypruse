# Bench findings

What the bench has shown so far, newest first. Raw results live in `bench/results/` (not committed); this file keeps the conclusions and the numbers behind them.

## 2026-11-08: first runs

Sonnet 5.5 (`claude-sonnet-5-5`), 5 tasks × 3 arms × 2 repeats, three desks at a time, plus a `fork-image` variant on 3 tasks × 2. hypruse source: fork at 30b5446, upstream at 6c28114. Desks had the workspace-block and accessibility-registry fixes.

| Arm | Pass | Median wall | Turns | Tool calls | Images | Median cost |
|---|---|---|---|---|---|---|
| bash | 8/10 | 31 s | 12 | 12 | 3.5 | $0.038 |
| upstream | 10/10 | 15 s | 8.5 | 7.5 | 2 | $0.026 |
| fork | 10/10 | 14 s | 11 | 10 | 2 | $0.026 |
| fork-image (3 hardest tasks only) | 5/6 | 47 s | 15 | 14 | 5.5 | $1.30 |

Two repeats per cell is enough to see whether things work, not to rank fork against upstream. Timings ran three at a time, so they share the machine.

### hypruse vs nothing

- Pixel precision is where it pays. `small-targets`: bash took a median 68 s and 24 turns and passed 1 of 2 (it hit 21 before 4). Both hypruse arms took 14 s and 6 turns and passed 2 of 2 with no misses.
- Accessible forms are a wash. Bash filled the GTK form with `wtype` and Tab in 12 s, as fast as `click_ui`.
- Window management is a wash too, as expected: both have `hyprctl`.
- Bash failed one background-picker run quietly: it re-applied the same wallpaper and said DONE.
- hypruse's tool definitions and instructions cost input tokens on every turn: `move-window` used 31k input tokens against bash's 8k over 3-4 turns. It still came out cheaper overall by needing fewer turns on the hard tasks.

### fork vs upstream

No difference on these tasks; none of them exercise what the fork changed (desk targeting, SUPER keycodes, session discovery). The next tasks need to: a SUPER combo the agent has to type, a task that needs `target`, an agent working beside a "human" in background mode.

### Inline screenshots cost 15-18× more on the same tasks

`HYPRUSE_SCREENSHOT_MODE=image` (the `fork-image` arm) sends inline image blocks instead of a path the agent `Read`s. The model did see them (one run described the new wallpaper correctly), but input tokens went from 73k to 268k on `small-targets` and from about 0.5-1M to 2.3-9.6M on `background-picker`. Claude Code 2.1.319 still sends something far bigger than the picture for an inline MCP image. Median cost per trial went from $0.026 to $0.40 (`small-targets`), $0.088 to $1.37 (`files-folder`) and $0.12 to $2.25 (`background-picker`). Keep the file default.

### Leads for the fork

- `use_bind` failed 4 of 4 times (both arms): every agent tried `SUPER+SPACE` first and got `hypruse has no Lua form for 'HL.Dispatcher(global)'`, because Hyprland 0.57 lists Omarchy's binds as `HL.Dispatcher(kind)` or a bare function. Agents then fell back to `launch omarchy-menu` or Bash. **Fixed** (b838b02): Lua binds are pressed with the layout's real keycodes; `use_bind SUPER+SPACE` opens the Omarchy menu in a desk.
- The fork's `pointer` and `keyboard` looked slower (941 ms and 1,038 ms against 261 ms and 591 ms). **Not a regression**: split by `then`, the bare actions take 80-120 ms in both arms, and all the time is `then='screenshot'`, which waits for two identical frames (up to 2 s) so it doesn't capture mid-animation. Fork agents asked for it more often, mostly on the animated Omarchy menu.
- `click_ui` averaged 430-590 ms. It's the most-used acting tool on GTK tasks, so it's still worth profiling.
- Every desk stop crashed the desk's `xdg-desktop-portal-hyprland` (a crash toast on the host each time) and left 2-3 processes behind. **Fixed** (e926a9e).

### The harness itself

- A check compared wallpaper paths, and the seeded desk's "before" path pointed into the host's theme directory, so re-applying the same image passed. Fixed to compare names; that trial was rescored by hand. New checks need the both-ways test in the README.
- Two `org.omarchy.agent` windows opened on the host during the first three trials. No trial sent the only bind that opens one (`SUPER+SHIFT+CTRL+A`), so it was most likely the human, but with three trials at once the watcher can't say.
