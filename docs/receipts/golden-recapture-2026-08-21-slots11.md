# Roadmap session 4 batch F receipt — 2026-08-21

Champions: Quinn, Rek'Sai, Renekton, Rengar, Riven.

Golden compare after the batch: IDENTICAL (zero diffs) — Quinn W, Rek'Sai P,
Renekton P, Riven E are label-only reclassifications (packets already
declared no_damage; MODULE_COVERAGE lagged), no recapture needed.

Rengar R (Thrill of the Hunt) stays OPEN (out_of_scope) as a genuine gap,
not a label fix: the bin's Ambush attack carries a real unmodeled formula
(BonusDamage StatByCoefficient mStat=2 coeff=1.0) with a two-front authority
conflict — damage-stat basis (bin bonus-AD coefficient vs wiki total-AD
text) and armor-shred array shape (bin 7-value DataValues vs wiki 3-value
[15,20,25]) — and the engine has no marked-target/Unseen Predator
proc-condition kernel. Documented in the module ASSUMPTIONS per the
Dr. Mundo precedent (slots7.md).
