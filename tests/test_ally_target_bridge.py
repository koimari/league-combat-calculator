"""The wiki ally-target bridge in ``scripts/extract_atoms.py``.

The CharacterRecord binaries carry almost no ``mTargetingTypeData``, so every
heal, shield and buff used to resolve to ``self`` and an ally-targeted heal
was indistinguishable from a self-heal. The bridge re-reads such an atom as
``ally`` when the cached wiki text for its slot grants a benefit *to* an ally.
These tests pin the direction rule, the eligibility rule and the corpus rows
they produce.
"""

import json
from pathlib import Path

from scripts.extract_atoms import (
    ENEMY_HEAL_ATOMS,
    _ally_sentence,
    ally_targeted,
    load_wiki_ally_slots,
    wiki_object_slot,
)

ATOMS = Path("data/atoms")


def _atoms(champion: str) -> list[dict]:
    return json.loads((ATOMS / f"{champion}.atoms.json").read_text(encoding="utf-8"))


def _policy(champion: str, behavior: str, atom_id: str) -> str | None:
    for atom in _atoms(champion):
        if atom["behavior"] == behavior and atom["atom_id"] == atom_id:
            return atom["target_policy"]
    return None


def test_a_benefit_granted_to_an_ally_is_an_ally_sentence():
    assert _ally_sentence(
        "Annie grants herself or the target allied champion and Tibbers a shield."
    )
    assert _ally_sentence("Nami heals allies and deals magic damage to enemies.")
    assert _ally_sentence(
        "Lulu casts erratic magic upon the target allied champion, granting bonus attack speed."
    )


def test_an_ally_who_is_the_source_of_the_benefit_is_not_a_recipient():
    # The benefit flows to the caster, not from it: reading these as
    # ally-targeted would put an ally policy on the receiver's own buff.
    assert not _ally_sentence("Whenever Lucian is healed or shielded by an ally")
    assert not _ally_sentence("damaged below 50% by him or an allied source")
    assert not _ally_sentence(
        "Allied champions triggering this effect grant Lucian Vigilance"
    )


def test_a_sentence_needs_both_an_ally_and_a_benefit():
    assert not _ally_sentence("Deals magic damage to enemies hit.")
    assert not _ally_sentence("Nearby allied champions gain sight of the area.")
    assert not _ally_sentence("")


def test_only_a_self_read_benefit_atom_is_re_read():
    slots = {"W"}
    entries = [("W", "Ebb and Flow", None)]
    assert ally_targeted(
        "heal-shield.heal", "self", entries, slots, "nami", "NamiW", ""
    )
    # An explicit policy already resolved elsewhere is never overwritten.
    assert not ally_targeted(
        "heal-shield.heal", "enemy", entries, slots, "nami", "NamiW", ""
    )
    # Damage and control never become ally-targeted through this bridge.
    assert not ally_targeted(
        "damage.damage-instance", "self", entries, slots, "nami", "NamiW", ""
    )
    assert not ally_targeted(
        "crowd-control-mobility.slow", "self", entries, slots, "nami", "NamiW", ""
    )
    # Nor does a heal-family atom that lands on an enemy.
    for atom_id in ENEMY_HEAL_ATOMS:
        assert not ally_targeted(atom_id, "self", entries, slots, "nami", "NamiW", "")
    # A slot with no ally evidence keeps its policy.
    assert not ally_targeted(
        "heal-shield.heal", "self", entries, set(), "nami", "NamiW", ""
    )


def test_the_bridge_resolves_a_spell_object_to_its_wiki_slot():
    entries = [("W", "Ebb and Flow", None), ("Q", "Aqua Prison", "magic")]
    slot, _entry, _toks = wiki_object_slot(entries, "nami", "NamiW", "")
    assert slot == "W"
    slot, entry, _toks = wiki_object_slot(entries, "nami", "NamiAquaPrison", "")
    assert slot == "Q" and entry is not None
    assert wiki_object_slot(entries, "nami", "SomethingElse", "")[0] is None


def test_the_wiki_map_names_the_slots_that_benefit_an_ally():
    slots = load_wiki_ally_slots()
    assert "W" in slots["nami"], slots["nami"]
    assert "W" in slots["thresh"] and "E" in slots["morgana"]
    # Lucian's text only describes benefits he receives, so no slot qualifies.
    assert not slots["lucian"], slots["lucian"]


def test_the_corpus_carries_the_bridged_policies_with_their_evidence():
    assert _policy("nami", "NamiW", "heal-shield.heal") == "ally"
    assert _policy("soraka", "SorakaW", "heal-shield.heal") == "ally"
    assert (
        _policy("lulu", "LuluWBuff", "stack-transform-summon-resource.buff") == "ally"
    )
    assert _policy("thresh", "ThreshWShield", "heal-shield.shield") == "ally"
    bridged = [
        atom
        for atom in _atoms("nami")
        if atom["behavior"] == "NamiW" and atom["atom_id"] == "heal-shield.heal"
    ]
    assert bridged and bridged[0]["provenance"]["evidence"].endswith("+wiki-ally")
    # A champion the bridge does not reach keeps self-read benefits.
    assert all(atom["target_policy"] != "ally" for atom in _atoms("lucian"))
