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

The scratch home is seeded with `~/.config/omarchy`, `~/.config/hypr`, terminal and GTK configs, the bash dotfiles, and `~/.local/state/omarchy` minus `clipboard-history.json` and `clipboard-images` (211 MB of your clipboard; private and not needed). `~/.local/share/fonts` is symlinked.

The PATH guards sit at `$XDG_RUNTIME_DIR/hypruse/desks/<name>/bin`, first on the desk's `PATH`. Omarchy's bash bootstrap only puts mise's command-wrappers directory ahead of them, so they also hold in the `bash -lc` shells the Omarchy shell spawns (checked with `command -v` from a login shell launched in the desk). The guards were tested against fake `systemctl`/`loginctl`/`uwsm`/`1password` binaries, never the real ones.

What a desk doesn't isolate: hardware and system services. Audio (PipeWire), network, Bluetooth, brightness and power profiles are the real machine. Opening the Audio panel in a desk showed the laptop's real devices and volume.

### Verified in an Omarchy desk

- The bar, dock, wallpaper and theme come up (shell answers `omarchy-shell shell ping`).
- Clicking the bar's volume icon opens the Audio panel.
- `omarchy-notification-send -u normal` on the desk's bus shows a toast in the desk; `omarchy-shell notifications count` went 0 → 1 in the desk and stayed 0 on the host.
- `SUPER+SPACE` through hypruse's virtual keyboard opens the Omarchy menu inside the desk while the host's focus stays where it was.
- The host's `systemctl --user show-environment` still has the host `WAYLAND_DISPLAY` and signature after start.
- The desk's `xdg-desktop-portal-hyprland` has the desk's signature and `wayland-2`.

### Open issues

- `/etc/omarchy.conf` exports `OMARCHY_PATH`, and `default/bash/env-bootstrap` sources it in every login shell. A desk started with `--omarchy-path <worktree>` has the worktree in the shell's own env, but every `bash -lc` the shell spawns switches back to the installed checkout. Testing a branch's commands in a desk needs Omarchy's bootstrap to keep an `OMARCHY_PATH` that's already set.
- `omarchy-system-lock` still `pkill`s screensavers by path, machine-wide.
- `uwsm app` passes through to the real uwsm, which launches into the user's systemd session. Untested what env those apps get.
