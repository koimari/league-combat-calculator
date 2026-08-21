# Golden recapture — roadmap session 4 batch C, 2026-08-21

Champions: Jarvan IV, Jayce, Kog'Maw, Lissandra, Lucian (one out_of_scope
slot each). Pre-recapture compare: 22 diffs, partitioned exactly 18 Jarvan
(17 fight-scenario zero rows + 1 baseline row for the newly emitted slot) +
1 Jayce + 1 Kog'Maw + 1 Lissandra + 3 Lucian, zero unattributed.

Numeric movement: NONE in damage totals. The only non-zero-row diffs are
Lucian E's baseline row gaining its sourced cooldown (0.0 -> 16.0; the
no-formula parser hardcodes 0.0, the closure reads the ability JSON row -
same documented quirk as Singed R / Olaf R) and its detail string moving
from the generic no-formula prose to the sourced ability text.

Per-champion dispositions live in each module's ASSUMPTIONS with sourced
evidence; per-champion test counts in /tmp/session4c-progress.txt.

Recapture executed after this attribution; compare re-verified identical.
