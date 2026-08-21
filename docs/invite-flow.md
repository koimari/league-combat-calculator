# Scryglass Invite Flow (P1a)

How beta invites are issued, what an invitee sees from first link to first
calculation, and how invite batches rotate. Companion to the operator docs
(`docs/beta-operations.md`, `docs/deploy-runbook.md`) and the P0a auth layer
(`src/app.py`: `_invite_codes`, `auth_login`, `api_auth_invite`).

## 1. How an invite is issued

Invites are **code batches configured by the operator**, not per-user
database rows. Everything lives in two environment variables:

| Variable | Purpose | Example |
|---|---|---|
| `SCRYGLASS_AUTH_USERS` | JSON map of research accounts → scrypt password hashes | `{"BetaResearcher": "scrypt$..."}` |
| `SCRYGLASS_INVITE_CODES` | Comma-separated batch of invite codes | `BETA-2026, PRESS-CLUB` |

Issuing an invite is two steps:

1. **Create the account** — add `"Username": "<scrypt-hash>"` to
   `SCRYGLASS_AUTH_USERS` (generate the hash with the scrypt tooling; the
   value must start with `scrypt$`).
2. **Share a code from the batch** — send the invitee one code from
   `SCRYGLASS_INVITE_CODES` **plus** their account name and the
   research-account password you set.

Matching rules (see `src/app.py::_invite_codes`):

- Codes are trimmed, deduplicated, and matched **exactly** — `BETA-2026` and
  `beta-2026` are distinct codes.
- An unset/empty `SCRYGLASS_INVITE_CODES` keeps the deployment in
  password-only mode (no invite field, no invite gate).
- Invite gating is active only when the auth gate is on **and** codes exist
  (`_invite_mode()`).

## 2. What the invitee sees

The invitee journey, end to end:

1. **Beta landing** — any unauthenticated visit to `/` redirects to
   `/auth/login` (the beta landing page). It explains the product and shows
   the sign-in card.
2. **Code + password** — the form asks for three fields in invite-gated
   deployments:
   - **Invite code** (the batch code they were sent),
   - **Research account** (their username),
   - **Password** (their research-account password).
   The invite code is validated first (401 + *“Enter a valid invite code.”*
   on a bad code), then the credentials. The validated code is stored in the
   signed session cookie so every later request carries its invite source
   (`/auth/status` → `user.invite`).
3. **First-run overlay** — after login the calculator loads and, on first
   browser visit (`localStorage` `scryglass_onboarded` not yet set), the
   welcome overlay explains champion setup, build setup, and result proof. It
   is dismissible (Skip / × / Escape) and never blocks. The full walkthrough
   is in `docs/onboarding-guide.md`.
4. **The calculator** — the invitee lands in the analyst view (the app;
   per-slot Best-in-slot covers "best next item").

The pre-auth surface stays public by design: `/healthz`, `/api/health/*`,
`/privacy`, `/terms`, `/riot-disclaimer`, `/api/auth/invite`,
`/api/metrics/event`, and all `/auth/*` routes. Everything else is gated
(302 → login) until the session exists.

## 3. Invite rotation

Rotate a batch when any of these happens:

- **A code leaks or appears in public** (issue tracker, pastebin, stream) —
  remove it from `SCRYGLASS_INVITE_CODES` immediately. Because codes are
  matched exactly against the configured list, deleting the code revokes it
  for every future login.
- **A cohort closes** — e.g. after a review wave, replace the batch with a
  new code so distinct waves stay separable in `/auth/status` (the session
  records which code was used).
- **The account list changes** — remove the account from `SCRYGLASS_AUTH_USERS`
  (or rotate its password hash) and re-deploy; existing sessions expire on
  the auth TTL.

Rotation procedure (per `docs/deploy-runbook.md`):

1. Edit `SCRYGLASS_INVITE_CODES` (and `SCRYGLASS_AUTH_USERS` if accounts
   changed) in the deployment environment.
2. Redeploy / restart the app — the env is read per request
   (`_invite_codes()` is stateless), so no migration or cache flush is
   needed.
3. Verify with `curl https://<beta-host>/api/auth/invite` (reports
   `invite_required` / `configured`) and confirm the old code now returns
   `401 Invalid invite code`.
4. Tell invitees with the revoked code to request a fresh one; do **not**
   re-share old codes once rotated.

### Session and monitoring notes

- **Sessions are signed cookies** (`SCRYGLASS_AUTH_SECRET`), TTL-bounded, and
  record `username` + `invite`. Logging out deletes the cookie; rotating the
  secret invalidates all sessions (planned maintenance only).
- **The validation API** (`POST /api/auth/invite`) checks a code without
  logging in: `200 {"valid": true, "invite": ...}` for a configured code,
  `401` unknown, `503` when no codes are configured. It is for operators and
  API clients — the landing page ships no JavaScript (`script-src 'self'`),
  so its form posts the code with the credentials to `/auth/login`, which
  validates the code first.
- **Audit trail:** `/auth/status` exposes the current session's invite code;
  use it (or app logs) to attribute a session to a cohort.

## 4. Failure modes and fallbacks

| Situation | Behavior | Operator action |
|---|---|---|
| Wrong invite code | 401 on the landing page; no session | Re-send the correct batch code |
| Code removed mid-batch | Existing sessions keep working until TTL; new logins rejected | Rotate + notify |
| `SCRYGLASS_INVITE_CODES` unset | Password-only mode; no invite field | Intended fallback for internal deploys |
| Auth env misconfigured | 503 with a setup error, never a silent open door | Fix env per `docs/deploy-runbook.md` |
