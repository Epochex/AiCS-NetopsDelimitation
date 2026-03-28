# Frontend Runtime Console Guardrails

When you edit anything under `frontend/`, optimize for runtime semantics first and visuals second.

## Required Delivery Pipeline

Every frontend task must follow this order:

1. `state-first`
   Update `frontend/stories/runtime-ui-states.json` and any relevant fixture or runtime contract before changing layout-heavy UI.
2. `browser-required`
   Every UI-affecting change must be checked in a real browser.
   Prefer Playwright MCP first.
   If Playwright MCP fails because of `root` / Chromium sandbox startup, use an explicit fallback browser run and record that fallback was used.
3. `screenshot-required`
   Every UI-affecting change must leave at least one screenshot artifact for review.
4. `rubric-required`
   Every frontend review must include a short critique that covers:
   - result-first readability
   - process traceability
   - motion semantics
   - evidence density
   - operator usefulness
5. `transport-aware`
   Separate design defects from data defects and proxy/transport defects.
   Never call a half-loaded `2088` page a design failure unless CSS/JS transport has been verified first.
6. `golden-states`
   Key runtime states should be preserved as state stories and screenshot references so future iterations do not regress silently.
7. `mcp-as-judge`
   MCP is not only for clicking buttons; use browser tooling for visual judgement, interaction replay, and render verification.

## Priority Order

1. Lead with the current slice.
2. Show where the event is in the lifecycle.
3. Keep evidence and control boundaries explicit.
4. Only then improve density, motion, and styling.

## Required Guardrails

- Do not turn this UI into a generic admin dashboard.
- Do not flatten all sections into equal-weight overview cards.
- Do not fake live progress where the backend only exposes a reserved boundary.
- Do not use animated meters for static evidence or manual-only stages.

## State Semantics

- `timestamp`: marks when a real transition was observed.
- `duration`: only represents measured transition timing.
- `gate`: only represents threshold progress toward a trigger.
- `status`: represents stable posture, not motion.
- `reserved`: represents a visible future control boundary and must stay visually constrained.

## Source Of Truth

- Runtime console data comes from `frontend/src/types.ts` and the live gateway snapshot.
- Compare-mode data comes from `frontend/fixtures/compare/*.json`.
- Component state boundaries come from `frontend/stories/runtime-ui-states.json`.
- Semantic mapping rules live in `.agents/skills/netops-frontend-runtime-ui/references/runtime-ui-map.md`.

## Review Loop

- Validate with `npm run build` before closing the loop.
- If the task changes layout, motion, language, or interaction hierarchy, update the relevant state stories first.
- Run a real browser check before closing the loop.
- Save at least one screenshot for review and mention whether it came from Playwright MCP or a fallback browser run.
- Include a short UX critique, not only code or test output.
- If browser review runs under `root` and Playwright MCP hits sandbox startup failure, use a direct Playwright fallback with `chromiumSandbox: false` and record that the fallback was used.
