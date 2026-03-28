# Frontend Runtime Console Guardrails

When you edit anything under `frontend/`, optimize for runtime semantics first and visuals second.

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
- If browser review runs under `root` and Playwright MCP hits sandbox startup failure, use a direct Playwright fallback with `chromiumSandbox: false` and record that the fallback was used.
