"""navitok command wrapper (v0.12.1): run a command and trim its long output.

The PostToolUse trimming hook only sees commands that succeed: Claude Code fires
PostToolUseFailure for a Bash command that exits non-zero, and that event cannot
replace the output. Failing tests and builds are exactly the output worth
trimming, so this wrapper runs the command itself:

  python scripts/run.py [--max-lines N] -- CMD [ARG ...]   run CMD with ARGs (no shell)
  python scripts/run.py [--max-lines N] -- "CMD | ..."     one argument: run it in the shell

It waits for the command, then prints its stdout and stderr, each trimmed with
the same trimmer as the hook (`trim_output.trim_text`) when longer than
`max_lines`. If anything was trimmed, the full output goes to
`.navitok/logs/` and a marker line names that log. The exit code is the
command's own (127 if it could not be started).

Calling the wrapper is an explicit choice, so it trims whether or not
`trim_output` is on; overrides in `.navitok/config.json` (`max_lines`, `head`,
`tail`, `context`, `keep_logs`) are used when present. The project folder is
`$CLAUDE_PROJECT_DIR`, else the current directory. No hook is involved, so it
cannot race other hooks (e.g. Graphify's) and there is no rewritten call for auto
mode to deny. Stdlib only.
"""

from __future__ import annotations

import json
import locale
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trim_output  # noqa: E402

USAGE = "usage: run.py [--max-lines N] -- CMD [ARG ...]"


def options(project_dir, max_lines=None):
    """Trim settings: DEFAULTS, then config.json overrides (even when the hook is off)."""
    opt = dict(trim_output.DEFAULTS)
    try:
        cfg = json.loads((Path(project_dir) / ".navitok" / "config.json").read_text(encoding="utf-8"))
        raw = cfg.get("trim_output") if isinstance(cfg, dict) else None
    except (OSError, ValueError):
        raw = None
    if isinstance(raw, dict):
        for k in opt:
            v = raw.get(k)
            if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                opt[k] = v
    if max_lines is not None:
        opt["max_lines"] = max_lines
    return opt


def decode(data):
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode(locale.getpreferredencoding(False) or "utf-8", errors="replace")


def parse(argv):
    """Return (max_lines, command list) or raise ValueError."""
    max_lines = None
    i = 0
    while i < len(argv) and argv[i] != "--":
        if argv[i] == "--max-lines" and i + 1 < len(argv):
            max_lines = int(argv[i + 1])
            i += 2
        else:
            raise ValueError(f"unknown option: {argv[i]}")
    cmd = argv[i + 1:]
    if not cmd:
        raise ValueError("no command given")
    return max_lines, cmd


def run(cmd, project_dir, max_lines=None):
    """Run cmd; return (exit code, stdout text, stderr text) as they should be shown."""
    shell = len(cmd) == 1
    try:
        proc = subprocess.run(cmd[0] if shell else cmd, shell=shell, capture_output=True)
    except OSError as e:
        return 127, "", f"navitok run: cannot start {cmd[0]!r}: {e}\n"
    code = proc.returncode
    if code < 0:  # killed by a signal (POSIX): use the shell's convention
        code = 128 - code
    out, err = decode(proc.stdout), decode(proc.stderr)
    try:
        opt = options(project_dir, max_lines)
        res = {"stdout": trim_output.trim_text(out, opt), "stderr": trim_output.trim_text(err, opt)}
        if any(res.values()):
            shown_cmd = cmd[0] if shell else subprocess.list2cmdline(cmd)
            log = trim_output.save_log(project_dir, shown_cmd, out, err, opt, "run")
            shown = trim_output.shown_path(log, project_dir)
            if res["stdout"]:
                out = trim_output.marked("stdout", res["stdout"], opt, shown) + "\n"
            if res["stderr"]:
                err = trim_output.marked("stderr", res["stderr"], opt, shown) + "\n"
    except Exception:  # never hide the command's output because trimming failed
        pass
    return code, out, err


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        max_lines, cmd = parse(argv)
    except ValueError as e:
        print(f"{e}\n{USAGE}", file=sys.stderr)
        return 2
    project = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    code, out, err = run(cmd, project, max_lines)
    sys.stdout.buffer.write(out.encode("utf-8"))
    sys.stdout.flush()
    sys.stderr.buffer.write(err.encode("utf-8"))
    sys.stderr.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
