# Sourced by task setup and check scripts. They run with the desk's display,
# bus and scratch HOME, plus BENCH_STATE (a directory outside the desk's home
# for fixture output) and BENCH_FIXTURES.

# Start a program detached, so it outlives the setup script.
launch() {
  setsid -f "$@" >/dev/null 2>&1 </dev/null
}

# Wait for a window whose title (or class, with --class) matches exactly.
wait_window() {
  local field=title
  if [[ $1 == "--class" ]]; then
    field=class
    shift
  fi
  local want=$1 attempt
  for (( attempt = 0; attempt < 80; attempt++ )); do
    if hyprctl clients -j | jq -e --arg f "$field" --arg w "$want" 'any(.[]; .[$f] == $w)' >/dev/null; then
      return 0
    fi
    sleep 0.25
  done
  echo "no window with $field '$want'" >&2
  return 1
}

# The workspace id of the window with this title, or nothing.
window_workspace() {
  hyprctl clients -j | jq -r --arg t "$1" '.[] | select(.title == $t) | .workspace.id'
}

# The check's verdict: `pass DETAIL` or `fail DETAIL`, as one JSON line.
verdict() {
  local result=$1
  shift
  jq -nc --arg r "$result" --arg d "$*" '{result: $r, detail: $d}'
  [[ $result == "pass" ]]
}
