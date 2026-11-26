#!/bin/sh
# Run a navitok hook with the first working Python 3.10+.
# On Windows, `python3` may be a Microsoft Store alias that does not run, so
# each candidate is probed. Always exits 0: a hook must never break a session.
#
#   run.sh start            session recorder and calibration refresh (silent),
#                           then the handoff summary:
#                           its stdout goes to Claude's context, empty unless
#                           .navitok/HANDOFF.md exists
#   run.sh stop|end         session recorder, fully silent
#   run.sh prompt           schedule engine (UserPromptSubmit): its stdout is the
#                           Tier-1 line for Claude, usually empty
#   run.sh trim             output trimming (PostToolUse, Bash): JSON on stdout
#                           only when trimming is enabled and the output is long

# Fast off path for `trim` (it runs after every Bash call): decide "off" with
# shell builtins only, before any Python starts or `dirname` forks. Off means
# no config.json in the project dir or the hook's cwd turns trimming on: the
# file is missing, has no "trim_output" line, or every such line reads
# "trim_output":false once blanks are removed. Anything else (true, an object,
# an unusual layout) falls through to trim_output.py, which decides exactly.
trim_off() {
  for f in "${CLAUDE_PROJECT_DIR:-.}/.navitok/config.json" "./.navitok/config.json"; do
    [ -f "$f" ] || continue
    while IFS= read -r l || [ -n "$l" ]; do
      case $l in *trim_output*) ;; *) continue ;; esac
      while :; do
        case $l in *[' 	']*) l="${l%%[' 	']*}${l#*[' 	']}" ;; *) break ;; esac
      done
      case $l in *'"trim_output":false'*) ;; *) return 1 ;; esac
    done < "$f"
  done
  return 0
}
if [ "$1" = "trim" ] && trim_off; then
  exit 0
fi

dir="$(dirname "$0")/../scripts"
for py in python3 python; do
  if "$py" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" </dev/null >/dev/null 2>&1; then
    if [ "$1" = "prompt" ]; then
      "$py" "$dir/schedule.py" hook 2>/dev/null
    elif [ "$1" = "trim" ]; then
      "$py" "$dir/trim_output.py" hook 2>/dev/null
    elif [ "$1" = "start" ]; then
      # All three scripts need the same hook JSON, so read stdin once.
      payload="$(cat)"
      printf '%s' "$payload" | "$py" "$dir/hook_session.py" start >/dev/null 2>&1
      printf '%s' "$payload" | "$py" "$dir/calibrate.py" hook >/dev/null 2>&1
      printf '%s' "$payload" | "$py" "$dir/handoff.py" hook 2>/dev/null
    else
      "$py" "$dir/hook_session.py" "$@" >/dev/null 2>&1
    fi
    exit 0
  fi
done
exit 0
