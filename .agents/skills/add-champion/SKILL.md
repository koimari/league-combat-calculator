---
name: add-champion
description: Add or update a named LoL champion module, its source evidence, registry entry, and tests.
---

# Add a Champion

Every runtime champion has one authoritative home:
`src/calculator/champions/<name>.py`. There is no reviewed-batch or
implicit generic runtime lane. The generic parser is only for explicit
synthetic/development fixtures.

## Module contract

The named module must publish the fields validated by
`ChampionModuleContract` in `module_contract.py`:

- `parse_abilities` and the local `SLOTS` parser map.
- `OPTIONS` and `ASSUMPTIONS`, including every scenario boundary.
- `SOURCES`, loaded through `source_receipts.load_champion_sources()` when
  they come from generated full-entry evidence.
- `MODULE_COVERAGE` only when the derivation is wrong for the kit: the
  contract classifies every slot in `SLOTS` as `modeled` and the rest as
  `out_of_scope`; declare the full P/Q/W/E/R map (values `modeled`,
  `no_damage`, `out_of_scope`) when an emitted slot is a zero-damage or
  partial row. There is no review-status field; a registered module is
  a reviewed module.

If the module uses `build_packet_module()`, pass everything champion-specific
into that one call: tick counts, event certification (`single_hit_slots`
reaches packet and wiki_attribute rows), timings, assumptions, slot
replacements (`slot_parsers`, any slot or a new one), parsers that build on
the compiled row (`slot_wrappers`, a factory handed the compiled parser), the
slot surface and its order when it differs (`slot_order`), and `MODULE_CC`
(`cc_kinds`). Keep what it returns: never rebind `parse_abilities` or `SLOTS`
afterwards and never restate `PACKET_SPEC` — the contract reads the pin off
the compiled parser and refuses a module whose parser does not carry it.
Pin the accepted packet declaration with the module's `PACKET_SHA256`;
changed generated evidence must fail closed until the named module reviews
and accepts the new digest. Print the digest a module must pin:

```bash
python -c "from src.calculator.champions.packet_module import _packet_specs, packet_spec_sha256; print(packet_spec_sha256(_packet_specs()['Ahri']))"
```

Never add a champion-name exception table to the shared packet compiler.

Register the module once in `_CHAMPION_MODULES`. The registry,
`/api/config`, receipts, and audits derive their public view from the
validated module contract.

## Evidence and behavior

Build or refresh `static/reviewed-packets.json` and the named source receipt
asset with `scripts/build_reviewed_modules.py`; generated files are evidence,
not executable champion modules. A rebuild must leave unrelated champions
byte-identical or the change must explain every difference.

Also:

- Declare sourced item on-hit behavior and update
  `tests/test_spellblade_on_hit_matrix.py` when applicable.
- Classify every option in `_ROTATION_CLASSIFICATIONS`.
- Use `scripts/atomize.py abilities stats` for numerical extraction.
- Add focused parser and fight tests for every calculation.
- Confirm `scripts/full_entry_audit.py` reports the module contract and
  catches packet-evidence drift when packet evidence is used.

## Verify

Run the focused champion tests, then:

```powershell
python scripts/atomize.py abilities stats
pytest
pylint src/
python scripts/golden_snapshot.py compare scripts/golden_baseline.json
python scripts/champion_optimizer_matrix.py
python scripts/coverage_census.py run --output docs/coverage-census.json
```

A new name moves the census roster and CI compares that receipt exactly, so
the regenerated `docs/coverage-census.json` (~10 min) ships in the same commit.

When evidence inputs are available, set `LCC_WIKI_DB`,
`LCC_WIKI_QUERY`, and `LCC_AXWORD_SOURCE` to explicit local paths. Do not
add machine-specific defaults to repository code or documentation.
