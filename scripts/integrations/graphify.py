"""navitok works with Graphify: file-scope estimation (v0.11).

Detects a Graphify knowledge graph (graphify-out/graph.json and
GRAPH_REPORT.md) and reads it to estimate which files and how many lines a
task touches. The file count feeds estimate.py's files factor. When there is
no graph yet, it proposes a priced "build the map" release.

Read-only towards Graphify: graph files are opened for reading only and never
modified. No Graphify code is used or copied, and Graphify is never run from
here. Stdlib only, deterministic, never calls the model.

  graphify.py detect [--project-dir DIR]
  graphify.py scope  [--project-dir DIR] [--title TEXT]
  graphify.py apply  [--project-dir DIR]          fill task scope into plan.json
  graphify.py map    [--project-dir DIR] [--apply] the "build the map" release
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import estimate  # noqa: E402
import plan as planmod  # noqa: E402

OUT_DIR = "graphify-out"
GRAPH_FILE = "graph.json"
REPORT_FILE = "GRAPH_REPORT.md"
HELPER = "graphify"
MAP_RELEASE_ID = "map"

MIN_TERM = 4          # shorter title words are too generic to match nodes
MAX_SEED_NODES = 25   # matched nodes kept per task
DEFAULT_SPAN = 20     # lines for the last node in a file (no next node to measure to)
MAX_SPAN = 200        # one node never counts for more lines than this
LIST_FILES = 15       # file paths kept in a task's scope record

_WORD = re.compile(r"[a-z0-9]+")
_LINE = re.compile(r"L?(\d+)")
_STOP = {
    "with", "from", "into", "that", "this", "when", "then", "than", "them", "they", "have",
    "make", "makes", "add", "adds", "update", "updates", "support", "file", "files", "task",
    "tasks", "data", "test", "tests", "code", "using", "used", "uses", "each", "only", "also",
    "build", "write", "read", "change", "changes", "handle", "new", "the", "and", "for",
}
_SKIP_DIRS = {".git", ".hg", ".svn", OUT_DIR, ".navitok", "node_modules", "__pycache__",
              ".venv", "venv", "env", "dist", "build", ".mypy_cache", ".pytest_cache", ".tox"}
# Graphify extracts code with tree-sitter (no LLM). Everything else it reads
# goes through LLM extraction, which is what the map release pays for.
_DOC_EXT = {".md", ".rst", ".txt", ".pdf", ".docx", ".html", ".htm", ".png", ".jpg", ".jpeg",
            ".gif", ".webp", ".svg", ".mp3", ".wav", ".mp4", ".mov", ".webm"}
_CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".scala", ".c",
             ".h", ".cpp", ".hpp", ".cc", ".cs", ".rb", ".php", ".swift", ".lua", ".sh", ".ps1",
             ".ex", ".exs", ".jl", ".zig", ".groovy", ".m", ".f90", ".v", ".sv"}


class GraphifyError(ValueError):
    pass


# --- detection ----------------------------------------------------------------

def paths(project_dir="."):
    out = Path(project_dir) / OUT_DIR
    return out / GRAPH_FILE, out / REPORT_FILE


def present(project_dir="."):
    """True when the project has a Graphify graph. Cheap: one stat (used by hooks)."""
    return paths(project_dir)[0].is_file()


def detect(project_dir="."):
    graph, report = paths(project_dir)
    info = {"present": graph.is_file(), "graph": str(graph) if graph.is_file() else None,
            "report": str(report) if report.is_file() else None,
            "version": None, "nodes": None, "edges": None}
    if info["present"]:
        try:
            g = load_graph(graph)
            info.update(version=g["version"], nodes=len(g["nodes"]), edges=len(g["links"]))
        except GraphifyError:
            info["present"] = False  # unreadable: behave as if there is no graph
    return info


def load_graph(path):
    """Read graph.json (node-link JSON). Returns {"nodes", "links", "version"}."""
    try:
        with open(path, "r", encoding="utf-8") as fh:  # read-only, never written
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise GraphifyError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        raise GraphifyError(f"{path}: not a Graphify graph (no 'nodes' list)")
    links = data.get("links", data.get("edges")) or []
    meta = data.get("graph") if isinstance(data.get("graph"), dict) else {}
    return {"nodes": [n for n in data["nodes"] if isinstance(n, dict) and "id" in n],
            "links": [e for e in links if isinstance(e, dict)],
            "version": meta.get("graphify_version")}


# --- scope --------------------------------------------------------------------

def _terms(text):
    out = set()
    for w in _WORD.findall(str(text or "").lower().replace("_", " ")):
        if len(w) >= MIN_TERM and w not in _STOP:
            out.add(w)
            if w.endswith("s") and len(w) > MIN_TERM:
                out.add(w[:-1])
    return out


def _line(node):
    m = _LINE.match(str(node.get("source_location") or ""))
    return int(m.group(1)) if m else None


def index(graph):
    """Precompute per-node terms, line spans and adjacency. Pure."""
    by_file = {}
    for n in graph["nodes"]:
        if n.get("source_file") and _line(n) is not None:
            by_file.setdefault(n["source_file"], []).append(n)
    span = {}
    for nodes in by_file.values():
        nodes.sort(key=_line)
        for a, b in zip(nodes, nodes[1:] + [None]):
            s = (_line(b) - _line(a)) if b is not None else DEFAULT_SPAN
            span[a["id"]] = max(1, min(MAX_SPAN, s or DEFAULT_SPAN))
    terms = {}
    for n in graph["nodes"]:
        src = n.get("source_file") or ""
        terms[n["id"]] = _terms(n.get("norm_label") or n.get("label")) | _terms(Path(src).stem)
    adj = {}
    for e in graph["links"]:
        s, t = e.get("source"), e.get("target")
        if s is not None and t is not None:
            adj.setdefault(s, set()).add(t)
            adj.setdefault(t, set()).add(s)
    return {"nodes": {n["id"]: n for n in graph["nodes"]}, "terms": terms, "span": span, "adj": adj}


def scope(task, idx):
    """Estimate the files and lines a task touches.

    Seeds are nodes sharing at least half as many title terms as the best match
    (labels and file names). Lines are the seeds' own spans. Files are the
    seeds' files plus their direct neighbours' (callers and callees usually
    need a look or a change too). Returns None when nothing matches."""
    want = _terms(task.get("title")) | _terms(task.get("description"))
    explicit = {str(p).replace("\\", "/") for p in task.get("paths") or [] if p}
    scored = []
    for nid, node in idx["nodes"].items():
        score = len(want & idx["terms"][nid])
        if (node.get("source_file") or "") in explicit:
            score += 2
        if score:
            scored.append((score, nid))
    if not scored:
        return None
    best = max(s for s, _ in scored)
    keep = math.ceil(best / 2)
    seeds = [nid for s, nid in sorted(scored, key=lambda x: (-x[0], x[1])) if s >= keep][:MAX_SEED_NODES]
    seed_files = {idx["nodes"][n].get("source_file") for n in seeds} - {None, ""}
    near = set()
    for n in seeds:
        near |= idx["adj"].get(n, set())
    near_files = {idx["nodes"][n].get("source_file") for n in near if n in idx["nodes"]} - {None, ""}
    files = sorted(seed_files | near_files | explicit)
    return {"source": HELPER, "files": len(files), "lines": sum(idx["span"].get(n, DEFAULT_SPAN) for n in seeds),
            "nodes": len(seeds), "paths": files[:LIST_FILES],
            "terms": sorted(want & set().union(*(idx["terms"][n] for n in seeds)))}


def annotate(plan, graph):
    """Fill `files` and a `scope` record on open tasks that have no file count
    yet (in place). A file count Claude set by hand is never overwritten.
    Marks the plan as Graphify-helped. Returns the number of tasks scoped."""
    idx = index(graph)
    done = 0
    for rel in plan.get("releases", []):
        for task in rel.get("tasks", []):
            if task.get("status", "todo") in ("done", "skipped") or task.get("type") == "wrapup":
                continue
            if task.get("files") is not None:
                continue
            sc = scope(task, idx)
            if sc:
                task["files"] = sc["files"]
                task["scope"] = sc
                done += 1
    helpers = [h for h in plan.get("helpers") or [] if h != HELPER]
    plan["helpers"] = helpers + [HELPER]
    return done


# --- "build the map" release -------------------------------------------------------

def corpus(project_dir="."):
    """Count the files Graphify would read: code (AST, no LLM) vs other (LLM)."""
    code = other = 0
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in _CODE_EXT:
                code += 1
            elif ext in _DOC_EXT:
                other += 1
    return {"code": code, "other": other}


def map_release(counts):
    """A release that builds the graph, priced separately from the project's own work.
    Code-only corpora need no LLM (`graphify update .`); other files go through
    Graphify's LLM extraction inside the session, sized by how many there are."""
    if counts["other"] == 0:
        task = {"title": "Build the Graphify map (code only: `graphify update .`, no LLM)",
                "type": "config", "size": "S", "execution": "inline"}
    else:
        size = "S" if counts["other"] <= 20 else "M" if counts["other"] <= 100 else "L"
        task = {"title": f"Build the Graphify map (`/graphify .`, {counts['other']} non-code files "
                         f"through LLM extraction)",
                "type": "research", "size": size, "execution": "subagent"}
    task.update(id=f"{MAP_RELEASE_ID}-t1", status="todo", files=None)
    return {"id": MAP_RELEASE_ID, "title": "Build the map (Graphify)", "tasks": [task]}


# --- CLI -----------------------------------------------------------------------

def _load_graph_or_fail(project_dir):
    info = detect(project_dir)
    if not info["present"]:
        raise GraphifyError(f"no Graphify graph at {paths(project_dir)[0]}; see `graphify.py map`")
    return load_graph(info["graph"])


def _learned(project_dir, plan):
    return planmod.learned_types(planmod.load_config(project_dir), plan.get("helpers"))


def cmd_detect(args):
    info = detect(args.project_dir)
    if info["present"]:
        print(f"Graphify graph found: {info['nodes']} nodes, {info['edges']} edges "
              f"(graphify {info['version'] or 'unknown version'}).")
        print(f"Report: {'yes' if info['report'] else 'no'} ({OUT_DIR}/{REPORT_FILE})")
    else:
        c = corpus(args.project_dir)
        print(f"No Graphify graph ({OUT_DIR}/{GRAPH_FILE}). The normal navitok flow works without it.")
        print(f"Corpus: {c['code']} code files (no LLM), {c['other']} other files (LLM extraction).")
    return 0


def cmd_scope(args):
    idx = index(_load_graph_or_fail(args.project_dir))
    if args.title:
        rows = [(None, args.title, scope({"title": args.title}, idx))]
    else:
        _, plan = planmod._load_plan(args.project_dir)
        rows = [(t["id"], t["title"], scope(t, idx)) for r in plan["releases"] for t in r["tasks"]
                if t.get("type") != "wrapup"]
    for tid, title, sc in rows:
        head = f"{tid + '  ' if tid else ''}{title}"
        if sc:
            print(f"{head}\n  ~{sc['files']} files, ~{sc['lines']} lines ({sc['nodes']} nodes: "
                  f"{', '.join(sc['terms'])})\n  {', '.join(sc['paths'])}")
        else:
            print(f"{head}\n  no matching nodes (estimate keeps its default)")
    return 0


def cmd_apply(args):
    graph = _load_graph_or_fail(args.project_dir)
    path, plan = planmod._load_plan(args.project_dir)
    n = annotate(plan, graph)
    cfg = planmod.load_config(args.project_dir)
    threshold = planmod.threshold_for(cfg)
    priced, over = planmod.price(plan, threshold, _learned(args.project_dir, plan))
    planmod._write_json(path, priced)
    print(f"Scoped {n} task(s) from the Graphify graph; tasks with a file count already set were kept.")
    for rel in priced["releases"]:
        print(f"{rel['id']:<8} {planmod._rng(rel['est_pct']):>14}  conf {rel['confidence']:>3}  {rel['title']}")
    if over:
        print("OVER: " + ", ".join(f"{rid} {hi:.1f}%" for rid, hi in over) + f" > {threshold:.0f}%. "
              "ROADMAP.md not rendered.")
        return 1
    print(f"Wrote {planmod.write_roadmap(args.project_dir, priced, threshold)}.")
    return 0


def cmd_map(args):
    if present(args.project_dir):
        print("A Graphify graph already exists; no map release needed.")
        return 0
    rel = map_release(corpus(args.project_dir))
    cfg = planmod.load_config(args.project_dir)
    res = estimate.estimate(rel["tasks"], cfg["plan"])
    print(f"{rel['id']:<8} {planmod._rng(res['total_pct']):>14}  conf {res['confidence']:>3}  "
          f"{rel['tasks'][0]['title']}")
    if not args.apply:
        print("Priced separately from the project's work. Re-run with --apply to add it to plan.json.")
        return 0
    path, plan = planmod._load_plan(args.project_dir)
    if any(r["id"] == MAP_RELEASE_ID for r in plan["releases"]):
        print("plan.json already has a map release; left unchanged.")
        return 0
    plan["releases"].insert(0, rel)
    priced, _ = planmod.price(plan, planmod.threshold_for(cfg), _learned(args.project_dir, plan))
    planmod._write_json(path, priced)
    print(f"Added the map release to {path}. After building the graph run `graphify.py apply`.")
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):  # Windows defaults to the ANSI code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="navitok: works with Graphify graphs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("detect")
    sub.add_parser("scope").add_argument("--title")
    sub.add_parser("apply")
    sub.add_parser("map").add_argument("--apply", action="store_true")
    for p in sub.choices.values():
        p.add_argument("--project-dir", default=".")
    args = ap.parse_args(argv)
    try:
        return {"detect": cmd_detect, "scope": cmd_scope, "apply": cmd_apply, "map": cmd_map}[args.cmd](args)
    except (OSError, GraphifyError, planmod.PlanError, estimate.EstimateError) as exc:
        print(f"graphify: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
