# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary user: LS, a League analyst working quickly while researching online or testing a hypothesis. He needs almost no prose, rapid scenario setup, and an immediately legible A/B build decision. Secondary users can inspect the same result, but the interface should not be designed like a beginner tutorial.

## Product Purpose

The calculator answers: “Which build is best at this game state against these enemies and/or alongside these allies?” It compares Build A and Build B under a selected objective, with an optional game-state constraint such as time, gold, level, role quest, and legal inventory. The result must lead with the winner; calculations, event order, and provenance remain expandable proof.

## Positioning

It is a scenario calculator rather than a static build list: build value changes with the complete allied and enemy roster, ranks, roles, boots, timing window, and the modeled event order.

## Operating Context

Users configure one main champion, allies, enemies, levels, ability ranks, roles, boots, item slots, rotations, and auto-attack uptime, then compare the resulting team-fight ledger and item-specific output.

## Capabilities and Constraints

- Champion-specific modules and locally ingested Wiki data are the source of mechanics.
- Missing or uncertified event order must remain visibly unavailable rather than silently becoming a heuristic.
- The interface must keep a compact answer-first summary while preserving an optional audit trail.
- All numeric outputs are patch-pinned and must retain their source or modeling boundary.
- The current scope is a damage-result and survivability presentation pass; calculation behavior is out of scope unless a prototype exposes a blocking UI defect.

## Brand Commitments

The product is part of Scryglass. Existing content uses the Scryglass name, patch context, champion and item imagery, and a dark calculator surface. The user explicitly asked for ten materially different visual directions rather than small variations on the current red-and-black treatment.

## Evidence on Hand

- Incumbent route: `templates/index.html`, `static/css/style.css`, and `static/js/app.js`.
- Existing damage-breakdown prototypes: `prototypes/damage-breakdown/`.
- Representative event data in the damage-breakdown prototypes includes Akali as the main participant and Orianna as an enemy participant.

## Product Principles

1. The first viewport answers Build A or Build B for the selected objective.
2. Objectives are explicit and selectable: overall, kill pressure, survival, damage dealt, team utility, and other separately modeled goals.
3. Game state is a first-class constraint with an off state for theoretical comparisons.
4. Every selected champion participates in one coupled, event-ordered timeline; crowd control, shields, healing, recovery, and temporary state changes are data, not prose.
5. Assume selected actions land when the scenario says they do; do not pretend to predict actual player behavior.
6. Show qualified results with a compact warning when mechanics are incomplete; never silently substitute a heuristic.
7. Use visual comparison first. Hide calculations, source text, and explanatory copy behind deliberate expansion.
8. The product should feel artistic, analytical, and involved—not like a tutorial, journal, or B2B dashboard.

## Accessibility & Inclusion

The web surface must remain keyboard navigable, preserve visible focus, maintain readable contrast, support narrow viewports, and never make color the only carrier of team, survival, or confidence state.

## Open Decisions

The ten directions in this request are exploratory prototypes. No visual direction is approved for production until the user selects one.
