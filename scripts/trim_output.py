"""navitok output trimming (v0.12): keep long Bash output from bloating the context.

A PostToolUse hook (matcher: Bash). When `.navitok/config.json` has
`trim_output` enabled and a command printed more than `max_lines` lines, the
hook saves the full output to `.navitok/logs/` and replaces what Claude sees
(`hookSpecificOutput.updatedToolOutput`) with a trimmed copy:

  - the first `head` lines (the command's own header),
  - every error-looking line, with `context` lines after it, and whole
    Python tracebacks,
  - the last `tail` lines (summaries such as "Ran 244 tests ... FAILED"),
  - repeated lines collapsed to one plus a count,
  - a marker line naming the full log.

PostToolUse never changes the command itself, so it cannot conflict with
another PreToolUse hook that rewrites or inspects it (e.g. Graphify's).

Off by default. Silent unless it trimmed something. Never blocks: any error
leaves the output untouched. Stdlib only, local files only.

  trim_output.py hook                  PostToolUse hook (stdin JSON)
  trim_output.py file PATH [--max-lines N]   trim a text file to stdout (manual check)
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULTS = {"max_lines": 120, "head": 10, "tail": 40, "context": 3, "keep_logs": 20}
LOG_DIR = "logs"
ERROR = re.compile(
    r"(error|exception|traceback|fail(ed|ure)?|fatal|panic|assert|denied|not found|"
    r"cannot|could not|unable to|segmentation fault|exit code [1-9]|\bE\s{2,}|^E\s)",
    re.I)
_NUM = re.compile(r"\d+")


# --- config --------------------------------------------------------------------

def settings(project_dir):
    """Trim settings from .navitok/config.json, or None when trimming is off.
    `trim_output` may be true/false or an object with `enabled` and overrides."""
    try:
        cfg = json.loads((Path(project_dir) / ".navitok" / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    opt = cfg.get("trim_output") if isinstance(cfg, dict) else None
    if opt is True:
        return dict(DEFAULTS)
    if isinstance(opt, dict) and opt.get("enabled") is True:
        out = dict(DEFAULTS)
        for k in DEFAULTS:
            v = opt.get(k)
            if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                out[k] = v
        return out
    return None


# --- trimming (pure) ------------------------------------------------------------

def _collapse(lines):
    """Collapse runs of lines that are equal after masking numbers (progress bars,
    '.....' rows, repeated warnings). Keeps the first and last of a run."""
    out, i = [], 0
    while i < len(lines):
        j = i
        key = _NUM.sub("#", lines[i]).strip()
        while j + 1 < len(lines) and _NUM.sub("#", lines[j + 1]).strip() == key:
            j += 1
        run = j - i + 1
        if run >= 3:
            out += [lines[i], f"  [... {run - 2} similar lines ...]", lines[j]]
        else:
            out += lines[i:j + 1]
        i = j + 1
    return out


def _keep_mask(lines, opt):
    n = len(lines)
    keep = [False] * n
    for k in range(min(opt["head"], n)):
        keep[k] = True
    for k in range(max(0, n - opt["tail"]), n):
        keep[k] = True
    in_tb = False
    for k, line in enumerate(lines):
        if line.startswith("Traceback (most recent call last)"):
            in_tb = True
        if in_tb:
            keep[k] = True
            # A traceback ends at its first unindented line after the header.
            if not line.startswith((" ", "\t", "Traceback")) and line.strip():
                in_tb = False
            continue
        if ERROR.search(line):
            for c in range(max(0, k - 1), min(n, k + 1 + opt["context"])):
                keep[c] = True
    return keep


def trim_text(text, opt):
    """Return (trimmed text, original line count, kept line count), or None when
    the text is short enough to leave alone."""
    lines = (text or "").splitlines()
    if len(lines) <= opt["max_lines"]:
        return None
    lines = _collapse(lines)
    keep = _keep_mask(lines, opt)
    out, gap = [], 0
    for line, k in zip(lines, keep):
        if k:
            if gap:
                out.append(f"  [... {gap} lines omitted ...]")
                gap = 0
            out.append(line)
        else:
            gap += 1
    if gap:
        out.append(f"  [... {gap} lines omitted ...]")
    return "\n".join(out), len((text or "").splitlines()), len(out)


# --- hook --------------------------------------------------------------------------

def _save_log(project_dir, payload, response, opt, now=None):
    now = now or datetime.now(timezone.utc)
    logs = Path(project_dir) / ".navitok" / LOG_DIR
    logs.mkdir(parents=True, exist_ok=True)
    tid = re.sub(r"[^A-Za-z0-9_-]", "_", str(payload.get("tool_use_id") or "bash"))[:40]
    path = logs / f"{now.strftime('%Y%m%dT%H%M%SZ')}-{tid}.log"
    cmd = (payload.get("tool_input") or {}).get("command", "")
    body = [f"$ {cmd}", "", "--- stdout ---", response.get("stdout") or "",
            "--- stderr ---", response.get("stderr") or ""]
    path.write_text("\n".join(body), encoding="utf-8")
    old = sorted(logs.glob("*.log"))
    for p in old[:max(0, len(old) - opt["keep_logs"])]:
        p.unlink(missing_ok=True)
    return path


def handle(payload, now=None):
    """Return the hook's JSON output (dict), or None to stay silent."""
    if payload.get("hook_event_name") not in (None, "PostToolUse") or payload.get("tool_name") != "Bash":
        return None
    response = payload.get("tool_response")
    if not isinstance(response, dict):
        return None
    project = payload.get("cwd") or "."
    opt = settings(project)
    if not opt:
        return None
    trimmed = {k: trim_text(response.get(k), opt) for k in ("stdout", "stderr")}
    if not any(trimmed.values()):
        return None
    log = _save_log(project, payload, response, opt, now)
    try:
        shown = log.resolve().relative_to(Path(project).resolve()).as_posix()
    except ValueError:
        shown = str(log)
    new = dict(response)
    for key, res in trimmed.items():
        if res:
            text, before, after = res
            new[key] = (f"[navitok: {key} trimmed {before} -> {after} lines; errors and the last "
                        f"{opt['tail']} lines kept; full output: {shown}]\n{text}")
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": new}}


def hook_main(stdin=None):
    try:
        raw = (stdin if stdin is not None else
               sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read().encode("utf-8"))
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        out = handle(json.loads(raw.decode("utf-8-sig", errors="replace") or "{}"))
        if out:
            sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
    except Exception:
        pass  # never break the user's session: the original output stays
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["hook"]:
        return hook_main()
    if argv[:1] == ["file"] and len(argv) >= 2:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        opt = dict(DEFAULTS)
        if "--max-lines" in argv:
            opt["max_lines"] = int(argv[argv.index("--max-lines") + 1])
        res = trim_text(Path(argv[1]).read_text(encoding="utf-8", errors="replace"), opt)
        print(res[0] if res else Path(argv[1]).read_text(encoding="utf-8", errors="replace"))
        return 0
    print(__doc__.strip().splitlines()[-2:][0], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
