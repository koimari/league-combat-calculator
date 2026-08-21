# Golden recapture — batch L on the PR #202 base, 2026-08-21

Context: roadmap batch L (Taliyah, Teemo, Tristana, Twitch, Udyr) was
rebased onto PR #202 (command-amp / gnar mega / missing runes), whose merge
had independently touched the same champions and recaptured golden. The
33 diffs below therefore compare the REBASED resolution against PR #202's
baseline. Partition: 2 Taliyah + 2 Teemo + 3 Tristana + 20 Twitch + 4 Udyr,
zero unattributed.

## Twitch (20) — an overstatement removed
PR #202's baseline applied Twitch Q's Element of Surprise attack speed
(+60 at rank 5) as a FIGHT-WIDE stat_buff, though the sourced buff lasts
6 seconds on breaking stealth. The rebased resolution drops the fight-wide
application in favor of the fail-closed windowed disposition (documented in
the module: sourced 40-60% values recorded, not applied; the timed-AS
window seam is the known kernel limitation). Downstream rows shrink
accordingly - e.g. on_hit_Kraken Slayer 252.01 -> 108.69 at L11 sustained
physical (fewer autos without the phantom fight-wide AS). This removes
inflated damage; it does not add any.

## Taliyah (2), Teemo (2), Tristana (3), Udyr (4)
Structural rows from the batch-L dispositions on the new base (zero-damage
rows, sourced detail strings, sourced cooldowns replacing no-formula 0.0
stubs) - per-champion evidence in the modules' ASSUMPTIONS and the batch-L
session log. No numeric damage-total movement outside Twitch.

Recapture executed after this attribution; compare re-verified identical.
The 7 cascade failures (p5 oracle x5, coupled allowlist, s6s7 oracle) all
keyed off the uncaptured baseline and clear with it.
