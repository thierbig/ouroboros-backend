# Frontend follow-ups

Backend-side findings that turned out to be frontend bugs. Filed here per the team design spec (`docs/superpowers/specs/2026-04-11-ouroboros-agent-team-design.md`, "Related projects" section). Fixers for this team are not allowed to edit the frontend; anything in this file is handed off for a separate follow-up.

## 1. `empty-resume-context` — UI sends wrong message type on resume

**Source:** `analysis/root_cause_other_buckets.md` §3 (`empty-resume-context` bucket)

**Symptom.** One session in the corpus (`69caf6db…`) begins with a single-word user message `"resume"` against a brand-new session that has no prior Solidity state, only a bun/ts scaffold. The backend receives it as a fresh prompt and the agent improvises a Coin Flip project from the template — not what the user meant.

**Cause.** The Nuxt 3 UI sends `{type: "message", content: "resume"}` when it should be sending `{type: "resume", session_id: "<prior-id>"}` to trigger the backend's resume flow. The backend has no way to know the user intended a resume — it sees a normal message with the word "resume" in it.

**Scope.** Frontend-only. The fix lives in `ouroboros-frontend/composables/useAgent.ts` (or whichever composable builds WS messages). No backend change needed.

**Evidence.** `analysis/dumps/69caf6db825fef911ec3ebd3.json` — first user message is the literal string `"resume"` and the session context is empty.

**Priority.** Low — only 1 session in 19 exhibits this, and the user experience (Coin Flip scaffold from scratch) is not catastrophic. Worth fixing eventually so "resume" means resume.

---

## No other frontend follow-ups emitted

All 7 stuck sessions in the corpus had backend-side root causes (confirmed by `analysis/session_termination_cause.md` — the "shape-A" and "shape-B" disconnect patterns originate in the backend's synchronous tool dispatch, not the frontend). No false positives from WebSocket transport mask genuine agent failures in the dumps we reviewed.
