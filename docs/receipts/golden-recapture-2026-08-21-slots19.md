# Golden recapture — final-slots: Warwick E, 2026-08-21

Warwick E (Primal Howl) implemented via the damage_modifier self_state
seam (Briar-E convention: full damage-class set — the cached notes name
no true-damage carve-out, unlike Alistar R's explicitly sourced
exclusion). Sourced: 35/40/45/50/55% reduction, 2.75s window
(timing.active_duration atom fdbc96dfbbb19a53), cooldown 15.0 replacing
the no-formula 0.0 stub.

Compare: 5 diffs = 3 Warwick baseline rows (cooldown, detail,
self_state_events) + 2 fingerprint counters (leaves 59946->59980,
numeric 46172->46181). Coupled surface probed: metadata-only (no bench
scenario carries Warwick). Zero damage-total movement.

Recaptured; compare re-verified identical.
