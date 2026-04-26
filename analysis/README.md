# analysis/

Working directory for the ouroboros agent-quality team (see
`docs/superpowers/specs/2026-04-11-ouroboros-agent-team-design.md`).

## Layout

| Path | Phase | Writer | Tracked in git? |
|---|---|---|---|
| `dump_stuck_sessions.py` | 1 | Investigator | Yes |
| `dumps/<session_id>.json` | 1 | Investigator | **No** (gitignored) |
| `taxonomy.md` | 1 | Investigator | Yes |
| `replay_set.json` | 1 | Investigator | Yes |
| `replay_driver.py` | 1 | Investigator | Yes |
| `baseline.md` | 1 | Investigator | Yes |
| `frontend_followups.md` | 1 | Investigator (if any) | Yes |
| `fixes/<bucket>.md` | 2 | Each fixer | Yes |
| `runs/<case>_<run>.json` | 3 | Validator | **No** (gitignored) |
| `validation.md` | 3 | Validator | Yes |

## Rules for teammates working in here

1. Read `../docs/superpowers/specs/2026-04-11-ouroboros-agent-team-design.md`
   before writing anything. It is the authoritative spec.
2. Raw session dumps and replay runs are PII-adjacent. Do not commit them.
   Do not paste their contents into chat messages outside the team.
3. The frontend repo at `c:\Users\thier\ouroboros-frontend\` is off-limits
   to fixers. The investigator may only read it to rule out frontend-caused
   false positives; any findings go in `frontend_followups.md`.
4. `replay_set.json` and `baseline.md` are written once by the investigator
   and are treated as read-only by fixers. Only the validator reads them
   in Phase 3.
