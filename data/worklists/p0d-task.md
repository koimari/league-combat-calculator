You are writing the PATCH-DAY RUNBOOK (P0d) for the Scryglass calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-p0d (branch codex/p0d-runbook). Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

CONTEXT: P3 built the automation (scripts/patch_regression.py compares the wiki cache against Community Dragon game files; data/staleness.json + STALE badges; scripts/patch_update.py re-pulls wiki data; scripts/issue_gate.py gates closures). The runbook must turn this into a repeatable OPERATING procedure with an SLA.

DELIVERABLES:
1. docs/patch-day-runbook.md — the complete day-0 procedure for a new LoL patch:
   - Step 0: detect the patch (cdtb versions; Riot patch notes).
   - Step 1: run scripts/patch_update.py run (re-pull wiki cache) → audit report.
   - Step 2: run scripts/patch_regression.py check → stale champions/items.
   - Step 3: triage stale items (SLA: within 24h of patch day, every stale flag is either re-certified (values updated + re-pinned) or marked with a documented boundary).
   - Step 4: re-capture golden with every diff explained; full gates; commit; push.
   - Step 5: clear staleness (re-run regression → stale=false) and confirm STALE badges disappear.
   - Escalation: champion kit rework (full module review needed — the E-series review checklist), item rework, new item added.
   - SLA table: detection < 4h, triage < 24h, full re-cert < 72h; stale badge stays visible until re-cert.
2. docs/beta-operations.md — weekly ops checklist (monitoring review, backup verification, validation-corpus bias scan via /api/validation, feedback triage) — 30 min/week.
3. A short CHANGELOG/template for patch-day announcements (docs/patch-announcement-template.md).
4. tests/test_p0d_runbook.py — assert the runbook files exist with the required sections (SLA, steps 0-5, escalation) and reference real scripts (patch_update.py, patch_regression.py, issue_gate.py) that exist on disk.

GATES: pytest -q full; black --check src/ tests/ (docs only, so no engine change); git diff --check.
COMMIT "docs(P0d): patch-day runbook + beta operations + announcement template" and PUSH origin/codex/p0d-runbook. Do NOT merge.
Reply to parent: runbook outline, SLA, escalation, test evidence, commit SHA.