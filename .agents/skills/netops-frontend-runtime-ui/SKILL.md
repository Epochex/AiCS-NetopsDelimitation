---
name: netops-frontend-runtime-ui
description: Use when editing the NetOps frontend runtime console, compare mode, state stories, lifecycle semantics, evidence panels, or frontend validation loops. Triggers on requests to refine the tactical runtime UI, add compare fixtures, tighten stage semantics, or build guardrails for frontend agentic work.
---

# NetOps Frontend Runtime UI

This skill keeps frontend work anchored to runtime behavior instead of vibe-only iteration.

## Use This Skill When

- Working in `frontend/`
- Tightening lifecycle or control-boundary semantics
- Adding or updating compare-mode fixtures
- Defining component state stories before homepage changes
- Reviewing whether UI blocks still map to real pipeline stages

## Workflow

1. Read `frontend/AGENTS.md` first.
2. Read `frontend/src/types.ts` and the smallest relevant UI file set.
3. For compare-mode work, load `frontend/fixtures/compare/*.json`.
4. For state-boundary work, load `frontend/stories/runtime-ui-states.json`.
5. For semantic mapping questions, read `references/runtime-ui-map.md`.
6. Implement the smallest useful UI change that keeps runtime semantics honest.
7. Validate with `npm run build`, then do a browser check if the change affects layout or motion.

## Non-Negotiables

- Current slice beats overview.
- Reserved boundaries stay reserved.
- Threshold progress is not elapsed time.
- Evidence panels must bind to real data fields, not hand-written summary prose.
- Compare mode must compare the same time window across branches.

## Validation Notes

- Build locally before wrapping up.
- In `root`-based sessions, native Playwright MCP browser startup may require a fallback because Chromium sandboxing can fail. If that happens, keep the limitation explicit and use a direct Playwright run only as validation fallback.
