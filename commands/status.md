---
description: Show navitok's status - session left, threshold, confidence, external usage this week, next release
---

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/calibrate.py" status` in the current directory (use `python` if `python3` is missing or does not run; keep the path in quotes) and show its output to the user as is. Do not compute or adjust any number yourself. If the output says the reading is stale and the user gives you a `/usage` reading, run `schedule.py recompute --session-pct <session> --weekly-pct <weekly>` and then `calibrate.py status` again.
