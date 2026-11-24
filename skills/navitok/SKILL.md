---
name: navitok
description: Plans a project into releases that fit the user's 5-hour session and weekly usage limits. Use when the user asks to plan work around their Claude usage limits, check whether a task fits the remaining session, or hand off at a clean stopping point. Work in progress; not functional yet.
---

# navitok (work in progress)

navitok is in early development (v0.0.1). This skill does not plan, estimate or schedule anything yet.

If this skill is invoked, tell the user that navitok is not functional yet and that planning arrives in a later release (see the project's `ROADMAP.md`). Do not invent estimates or usage numbers.

Planned flow (not implemented):

1. Plan: break a project into tasks and price each as a range of session %.
2. Check: before each task, confirm that the remaining session budget covers the task's upper estimate.
3. Hand off: end each session at a clean commit with a `HANDOFF.md` note.
