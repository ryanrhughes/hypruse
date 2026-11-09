# Desks

A desk is a nested Hyprland that hypruse drives instead of your own session. It runs as one window on the host, has its own seat (cursor, keyboard focus, clipboard), and can run the full Omarchy desktop. You keep working; the agent works in the desk.

This file is the running record of what we've learned building them on this fork. Findings carry the evidence that backs them, so they can be rechecked when Hyprland or Omarchy changes.

## Running one

```sh
contrib/hypruse-desk start omarchy1                 # full Omarchy, hidden on special:hypruse
contrib/hypruse-desk start scratch --profile bare   # empty Hyprland
contrib/hypruse-desk run omarchy1 -- hypruse desktop
contrib/hypruse-desk show omarchy1                  # toggle it into view on the host
contrib/hypruse-desk stop omarchy1 [--purge]        # --purge also deletes its scratch home
```

`run` sets `HYPRLAND_INSTANCE_SIGNATURE`, `WAYLAND_DISPLAY`, `DBUS_SESSION_BUS_ADDRESS` and `HYPRUSE_BACKGROUND=0` for the command. Apps the agent launches go through the desk's compositor, so they get the desk's `HOME` and bus from it.

hypruse itself can switch without `run`:

- The MCP `target` tool: `target()` lists desks, `target("omarchy1")` points every tool at that desk, `target("here")` goes back to the user's desktop. `desktop` carries a `target` key while a desk is the target.
- `HYPRUSE_TARGET=omarchy1` picks the target at startup, for the MCP server and the CLI verbs alike. A desk that isn't running is an error; it never falls back to `here`.

- The CLI verb `hypruse target` lists here and the desks; `hypruse target NAME` checks a desk is running. A verb is one process and can't switch the next one, so shell agents prefix each command with `HYPRUSE_TARGET=NAME` (the bundled skill says so).

On Ryan's machine the fork is registered as the `hypruse` MCP server for Claude Code (user scope, `~/.claude.json`) and Codex (`~/.codex/config.toml`), both pointing at `~/Work/hypruse/.venv/bin/hypruse`. `uv sync` installs the fork there in editable mode, so the server always runs the working tree, and an absolute path doesn't depend on the client seeing mise's `PATH`. Codex starts stdio servers with a stripped environment; a client with only `HOME`, `PATH` and `USER` still found the right monitors and switched to a desk and back, because of the discovery fix below. Omarchy keeps a separate Claude/Codex home per agent account (`omarchy-agent-account-home`); this registration is the default account only.

`src/hypruse/target.py` reads the desk's env file, takes only the four variables above from it (so a desk can't switch off a guard like `HYPRUSE_AUTH_GUARD`), and drops what was cached against the old compositor: the virtual pointer and keyboard, the config-manager probe, the strict-mode seat baseline. Launched windows are kept per target, since window addresses only mean something on the compositor that issued them.

State lives in two places:

- `$XDG_RUNTIME_DIR/hypruse/desks/<name>/`: env, pids, the generated `hyprland.lua`, the private bus socket, the PATH guards, and the compositor's stdout log.
- `~/.cache/hypruse/desks/<name>/home/`: the scratch home. It survives `stop` so a desk keeps its state between runs; `--fresh` reseeds it.

## Why a nested compositor

Hyprland 0.57 advertises exactly one `wl_seat`. Listing the registry on the live session shows `wl_seat 9` once and nothing else seat-shaped. Every pointer and keyboard, real or virtual, shares that seat, so an agent clicking on your session moves your cursor and steals your focus. There's no way to give an agent its own cursor on the live session until Hyprland grows multi-seat support. hypruse already has the client side for that (`HYPRUSE_SEAT` creates the virtual pointer on a named seat), so it lights up the day the compositor offers a second seat.

A nested Hyprland is a whole second compositor, so it has its own seat for free. The tradeoff is that it can't touch the windows on your session; whatever the agent works on has to be opened inside the desk.

## Findings

### A hidden desk doesn't render without `render_unfocused`

The host only sends frame callbacks to windows it's showing. A nested Hyprland that gets no frame callbacks never renders, and `grim -o WAYLAND-1` against it hangs until killed (we saw a 10 s hypruse timeout, then `timeout 5 grim` exit 124). The window was on host workspace 12 while the monitor showed 11.

The fix is a host window rule: `render_unfocused = true` on `class ^aquamarine$`. With it, captures of the hidden desk work (three in a row, exit 0). The very first capture right after adding the rule failed once with `failed to copy output`, then never again.

The launcher applies it as a named rule (`name = "hypruse-desk"`), so re-applying replaces the rule instead of stacking copies. The rule also floats the desk window at the desk size and sends it to the desk's host workspace `silent`, which keeps the nested output at a stable size. Without the float, the nested output tracked the tiled window and jumped between 1600x1000 and 1896x1030, which made screenshot coordinates stale.

The rule is runtime only (`hyprctl eval`); a host config reload drops it until the next `start`.

### Headless outputs inside a desk can't allocate buffers on N1x

`hyprctl output create headless` inside a nested Hyprland made an output stuck at 0x0. With a monitor rule it listed `1920x1080@60` but the log filled with `GBM: Failed to allocate a GBM buffer: bo null` / `Swapchain: Failed acquiring a buffer`. Tested on aarch64-n1x. A headless output would have been the cleaner way to keep a hidden desk rendering, so this is worth an aquamarine bug report once it's reproduced on x86.

### hypruse's background mode is wrong inside a desk

hypruse's automatic background mode opens new windows on the agent's workspaces (99 down to 90). Inside a desk, those are just off-screen workspaces of a compositor that's already the agent's, so the first test launched foot onto workspace 99, clicked an empty workspace 1, and typed into nothing. `run` sets `HYPRUSE_BACKGROUND=0`.

Related: `keyboard type` with no focused window reported "typed 57 characters" and the text went nowhere. hypruse should refuse or warn when nothing has keyboard focus.

### `hypruse doctor` false failure on layouts away from 0,0

The doctor's screenshot check captures region `0,0 8x8`. Ryan's monitors start at x=4620, so grim answers `supplied geometry did not intersect with any outputs`. Real captures work. The check should use a pixel inside the first monitor's logical rect.

### Session discovery paired one compositor's signature with another's display (fixed)

An MCP client starts its servers with a stripped environment (no `HYPRLAND_INSTANCE_SIGNATURE`, no `WAYLAND_DISPLAY`), so hypruse discovers them. The old discovery took the newest Hyprland instance's signature and, separately, the alphabetically first `wayland-*` socket. With a desk running, that was the desk's signature and the host's `wayland-1`: `desktop` described the desk while clicks and keys went to the host. It reproduced through a real MCP stdio client: after `target("here")`, `desktop` still listed the desk's single `WAYLAND-1` monitor.

Each instance's `$XDG_RUNTIME_DIR/hypr/<sig>/hyprland.lock` holds its pid and its Wayland socket, so `session.py` now takes the pair from one lock file. It skips desks listed under `hypruse/desks/*/env`, then prefers a top-level compositor over a nested one (a nested Hyprland's process carries its parent's `WAYLAND_DISPLAY` in `/proc/<pid>/environ`; the host's has none), then the newest. Instances whose lock pid is dead are ignored; stopped desks leave their directories behind. This bug exists upstream for anyone running more than one Hyprland.

### SUPER plus any key arrived as SUPER+Escape (fixed)

`keyboard key super+k` in a desk opened Omarchy's System menu (`SUPER+ESCAPE`), and so did `super+space`. wtype, and hypruse's own wire keyboard, upload a throwaway keymap holding only the combo's keys, numbered from evdev 1. Hyprland matched the bind on the raw keycode through the real layout, and evdev 1 is `KEY_ESC`.

Combos now go out on the active layout's full keymap (built with libxkbcommon from `hyprctl devices`, including Omarchy's own `omarchy:shift_caps_compose` option) at the codes a physical keyboard sends: `Super_L` 125, `k` 37, `space` 57. After the fix `super+k` opened Keybindings and `super+space` the Omarchy menu. On the host, the old behavior meant an agent pressing any SUPER shortcut opened the System menu, one `Return` away from Screensaver and two keys from Suspend.

Upstream's instructions say synthetic keys can't trigger compositor binds. On Hyprland 0.57 they can, and with real keycodes they trigger the right one. The wire keyboard also had never run on the default seat: `create_virtual_keyboard` needs a bound `wl_seat` (the pointer manager accepts null), and the seat has to be bound before the keyboard's id is allocated, because libwayland wants new ids in sequence.

### `use_bind` can't run Omarchy's binds

Under the Lua config manager a bind's action is a closure (`hyprctl binds` shows `HL.Dispatcher(exec_cmd) 342`), and hypruse has no way to invoke it from outside, so `use_bind SUPER+K` errors. Nearly every Omarchy bind is like that. Real key events are the way to fire them.

### Omarchy renumbered the agent's workspaces into the user's (fixed by default)

Omarchy gives every monitor a block of ten numbered workspaces (laptop 1-10, next monitor 11-20, and so on; `default/hypr/monitor-workspaces.lua`). On every reconcile (a monitor plugged or unplugged, a config reload, startup), a workspace with windows outside any monitor's block gets renumbered into the block of the monitor it sits on. hypruse's upstream default puts the agent's apps on 99 down to 90, which is block 9, a tenth monitor nobody has.

Tested in a desk with background mode on: `launch foot` opened on 99, then `hyprctl reload` in the desk moved it to 42, that monitor's slot 2, and the bar lit up workspace "2". On a laptop that docks and undocks, that happens to the user's real session every time.

Named workspaces have no number. Omarchy's reconcile only touches `id > 0` (`regular()`), and the bar skips `id <= 0`, so `name:agent` survived the reload and never showed in the bar. The fork's default is now `name:agent-1` to `name:agent-10`. Hyprland 0.57 reports a named workspace's `id` as `null` in `hyprctl -j workspaces`.

Background typing into the hidden agent terminal (`keyboard type ... --window ADDR`, delivered with `sendshortcut`) worked. A `--window` capture of it showed an empty terminal with no prompt, because foot stops drawing while hidden, so the capture was its last frame from before. Bringing the workspace forward showed the typed text. A hidden capture isn't proof that an action landed; in a desk, look at the window in the foreground instead.

### A desk's workspace 1 was workspace 41 (fixed)

Seeding copied the host's `~/.local/state/omarchy/monitors/`, where Omarchy records which block of ten each physical monitor owns. The host's monitors already held four blocks, so the desk's one output (`WAYLAND-1`) got the fifth: windows opened on 41, and a window an agent moved to "workspace 3" left the desk's block. Seeding now skips `monitors/`, so the desk's output gets 1-10 like a fresh install.

### Accessibility didn't work in a desk (fixed)

`hypruse ui` on any desk window failed with `Could not activate remote peer 'org.a11y.atspi.Registry': unit failed`, so `click_ui`, `ui` and `marks` were all dead in a desk. The desk's private session bus is a plain `dbus-daemon`, but the accessibility bus that `at-spi-bus-launcher` starts for it is a `dbus-broker`, and dbus-broker starts the services it activates through the user's systemd manager, in the host session's environment. Activating the registry that way failed, with nothing in the journal.

Running `/usr/lib/at-spi2-registryd` from the desk's environment with `AT_SPI_BUS_ADDRESS` set to the desk's a11y bus (`busctl --user call org.a11y.Bus /org/a11y/bus org.a11y.Bus GetAddress`) fixed it: the form fixture listed its two text boxes, checkbox, radios and button, and Nautilus listed its toolbar. The desk now writes `hypruse-desk-a11y` into its guard directory and runs it at `hyprland.start`. Apps register when they start, so an app started before the registry is up has no tree until it's restarted; `bench/run.py` waits for the registry before a task's setup.

### Stopping a desk crashed its portal and left processes behind (fixed)

Every desk stop put a "Process crashed: xdg-desktop-portal-hyprland" toast on the host: the desk's own portal segfaulted in `wl_proxy_marshal_flags` when its compositor exited under it (about 20 core dumps during one 30-trial bench run). Stopping also left two `inotifywait` watchers per desk (the shell's plugin watcher), the desk's accessibility bus and registry, all orphaned under the user's systemd: 83 processes after one evening.

`stop` now ends the desk's processes before its compositor: every one carries the desk's private bus address or, for services the bus activates, the desk's Hyprland signature, and nothing on the host has either. One `grep -lzxF` over `/proc/*/environ` finds them (a per-process loop took 55 s), TERM goes first, KILL catches stragglers after the compositor exits. A stop now takes about 2.5 s, with no core dump and nothing left.

### mise reinstalls tools inside a desk

mise keeps installs under `XDG_DATA_HOME`, and the desk's points at the scratch home, so the first `claude` run in a desk downloaded Claude Code again (3 s plus the network). The bench sets `MISE_DATA_DIR` back to the user's. The desk itself doesn't yet, so any mise-managed tool an app in the desk runs is fetched again on a fresh desk.

### Driving Omarchy's shell

- Menus and bar panels are full-screen overlay layers that take the keyboard grab: `omarchy-menu`, `omarchy-image-selector` (the theme carousel), and `omarchy-keyboard-panel` (the Audio panel and friends). hypruse's note that a launcher layer "covers this point" or "holds the keyboard grab" is accurate while one is open.
- A menu bound to a key takes about a second to map. Block on `wait_for layer_open --match omarchy-menu` instead of sleeping.
- Typing filters the menu: `super+space`, type `appearance`, `Return`, `Return` lands on the theme carousel.

### Speed

From the CLI, which pays Python startup on every call: `desktop` ~0.1 s, `screenshot` ~0.2 s, and click + type + Return + capture on a desk ~1.2 s across five invocations. The MCP server doesn't pay the per-call startup.

### Nested output scale

The desk renders at scale 1 into a host window on a scale-2 monitor, so it looks soft when you watch it. The agent's screenshots are fine (they're the desk's own pixels). Not fixed yet.

## The Omarchy profile

The desk loads Omarchy's Hyprland config from a scratch home and starts only the shell. Everything else Omarchy's session startup does would reach past the desk into the real session. These are the leaks we found and how the profile closes each one.

| Leak | What would happen | What the desk does |
|---|---|---|
| `default.hypr.autostart` runs `dbus-update-activation-environment --systemd --all` | The user's systemd and D-Bus activation env gets the desk's `WAYLAND_DISPLAY`/`HYPRLAND_INSTANCE_SIGNATURE`, so apps you start afterwards open in the desk | Marks the module loaded before `require("default.hypr.omarchy")`, so none of autostart runs (also skips first-run, power profiles, monitor watch, udiskie, `herdr server`, post-boot hooks) |
| Shared session bus | The desk shell competes with yours for `org.freedesktop.Notifications`, `StatusNotifierWatcher` and portals | Private `dbus-daemon` per desk |
| Bus started with the host env | Portals the desk activates connect to the host display; a screen share from the desk could capture your real screen | The bus starts with `WAYLAND_DISPLAY` and `HYPRLAND_INSTANCE_SIGNATURE` unset; the desk runs `dbus-update-activation-environment --all` (no `--systemd`) before starting the shell |
| Shared `~/.config` and `~/.local/state` | Theme switches and plugin settings in the desk rewrite your config and your shell reloads them | Scratch `HOME` plus explicit `XDG_CONFIG_HOME`/`XDG_STATE_HOME`/`XDG_DATA_HOME`/`XDG_CACHE_HOME` (they're set explicitly in the session env, so `HOME` alone isn't enough) |
| Idle timers | An idle desk runs `omarchy-system-lock`, which also runs `1password --lock` and kills screensavers machine-wide | `idle.lock` and `idle.screensaver` set to 0 in the scratch `shell.json` |
| System menu Logout | `omarchy-system logout` runs `uwsm stop`, which ends your real session | PATH guard: `uwsm stop` exits the desk instead |
| System menu Suspend/Reboot/Shutdown | `systemctl suspend`/`reboot`/`poweroff` on the real machine | PATH guards refuse power verbs in `systemctl`, `loginctl`, `shutdown`, `reboot`, `poweroff`, `halt`, and post a notification inside the desk |
| Anything run as root | A desk's theme switch rewrote `/etc/brave/policies/managed/color.json` and `/etc/chromium/...` through `omarchy-theme-set-browser-policy`'s passwordless sudo rule, so the user's real browser turned Vantablack black | PATH guards refuse `sudo`, `pkexec`, `run0`, `su`, `doas` |
| Herdr theme sync | `omarchy-theme-set-herdr-machines` pushes the theme to the user's other machines over ssh when the `herdr-theme-sync` toggle is on | Seeding drops that toggle from the scratch state |

The scratch home is seeded with `~/.config/omarchy`, `~/.config/hypr`, terminal and GTK configs, the bash dotfiles, and `~/.local/state/omarchy` minus `clipboard-history.json` and `clipboard-images` (211 MB of your clipboard; private and not needed). `~/.local/share/fonts` is symlinked. mise's state dir is copied too: its trust list lives there, and without it every shell in the desk warned that `~/.config/mise/config.toml` wasn't trusted.

The PATH guards sit at `$XDG_RUNTIME_DIR/hypruse/desks/<name>/bin`, first on the desk's `PATH`. Omarchy's bash bootstrap only puts mise's command-wrappers directory ahead of them, so they also hold in the `bash -lc` shells the Omarchy shell spawns (checked with `command -v` from a login shell launched in the desk). The guards were tested against fake `systemctl`/`loginctl`/`uwsm`/`1password` binaries, never the real ones.

What a desk doesn't isolate: hardware and system services. Audio (PipeWire), network, Bluetooth, brightness and power profiles are the real machine. Opening the Audio panel in a desk showed the laptop's real devices and volume.

### Verified in an Omarchy desk

- The bar, dock, wallpaper and theme come up (shell answers `omarchy-shell shell ping`).
- Clicking the bar's volume icon opens the Audio panel.
- `omarchy-notification-send -u normal` on the desk's bus shows a toast in the desk; `omarchy-shell notifications count` went 0 → 1 in the desk and stayed 0 on the host.
- `super+space` through hypruse's keyboard opens the Omarchy menu inside the desk while the host's focus stays where it was (after the keycode fix; before it, the System menu).
- A full theme switch through the UI (menu, Appearance, Theme, carousel, Return) changes the desk's theme and wallpaper. The host stayed on Tokyo Night, nothing under the host's `~/.config/omarchy` or theme state changed, and with the root guard `/etc/brave/policies/managed/color.json` kept its timestamp while the desk showed `Desk guard` toasts for the refused `sudo -n -l` probe and `pkexec` fallback.
- The leak this caught on the first run was undone by running `omarchy-theme-set-browser` on the host, which rewrote the policies from the host's theme (`#1a1b26`).
- The host's `systemctl --user show-environment` still has the host `WAYLAND_DISPLAY` and signature after start.
- The desk's `xdg-desktop-portal-hyprland` has the desk's signature and `wayland-2`.

### Open issues

- `/etc/omarchy.conf` exports `OMARCHY_PATH`, and `default/bash/env-bootstrap` sources it in every login shell. A desk started with `--omarchy-path <worktree>` has the worktree in the shell's own env, but every `bash -lc` the shell spawns switches back to the installed checkout. Testing a branch's commands in a desk needs Omarchy's bootstrap to keep an `OMARCHY_PATH` that's already set.
- `omarchy-system-lock` still `pkill`s screensavers by path, machine-wide.
- `omarchy-theme-set-browser` picks the browsers to refresh from the machine's whole process list, then runs `brave-origin --refresh-platform-policy --no-startup-window` in its own session, even when the policy write failed. In a desk that starts a second Brave on the desk's fresh profile, and `--no-startup-window` doesn't stop its first-run window. Omarchy-side fix: only refresh browsers in the caller's session, and skip the refresh when the policy didn't change.
- Theme switches also signal host apps (`killall -SIGUSR1 kitty`, `pkill -USR1 helix`, btop, ghostty, opencode, hunk, tmux). They reload their own, unchanged config, so it's harmless, but it's another machine-wide reach.
- `omarchy-theme-set-keyboard` sets real keyboard backlight colors through `asusctl` on ASUS ROG machines. Not installed here, so untested.
- `uwsm app` passes through to the real uwsm, which launches into the user's systemd session. Untested what env those apps get.
