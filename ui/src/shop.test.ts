import test from "node:test";
import assert from "node:assert/strict";
import { shopGroup, wikiText } from "./shop.ts";

test("shop groups follow source ranks despite unrelated tier values", () => {
  assert.equal(shopGroup({ rank: ["LEGENDARY"] }), "Legendary");
  assert.equal(shopGroup({ rank: ["EPIC"] }), "Epic");
  assert.equal(shopGroup({ rank: ["BASIC"] }), "Starter & Basic");
  assert.equal(shopGroup({ rank: null }), "Other items");
});
test("effect text preserves melee and ranged values plus unit tooltip", () => {
  const result = wikiText(
    "Deal {{as|{{rd|40% AD|20% AD}}|ad}} {{as|physical damage}} within {{tt|700 units|center to edge}}.",
  );
  assert.equal(
    result,
    "Deal 40% AD melee / 20% AD ranged physical damage within 700 units (center to edge).",
  );
});
test("source scaling expressions and reset branches survive conversion", () => {
  assert.equal(
    wikiText(
      "{{ap|(60/6)+10}}% {{as|AP}}\n[[Basic attack reset|Reset]] the attack.",
    ),
    "(60/6)+10% AP\nReset the attack.",
  );
  assert.equal(
    wikiText("{{pp|150 to 350|type=target's level|color=heal}}"),
    "150 to 350 (target's level)",
  );
});
test("source variables resolve and image/html markup remains text only", () => {
  assert.equal(
    wikiText("{{#vardefineecho:hollow_ibase|15}} + {{#var:hollow_ibase}}"),
    "15 + 15",
  );
  assert.equal(
    wikiText("[[File:Icon.png]]<b>Safe</b> &amp; plain"),
    "Safe & plain",
  );
});
