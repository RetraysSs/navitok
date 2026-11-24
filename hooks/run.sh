#!/bin/sh
# Run a navitok hook with the first working Python 3.10+.
# On Windows, `python3` may be a Microsoft Store alias that does not run, so
# each candidate is probed. Always exits 0: a hook must never break a session.
script="$(dirname "$0")/../scripts/hook_session.py"
for py in python3 python; do
  if "$py" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" </dev/null >/dev/null 2>&1; then
    "$py" "$script" "$@" >/dev/null 2>&1
    exit 0
  fi
done
exit 0
