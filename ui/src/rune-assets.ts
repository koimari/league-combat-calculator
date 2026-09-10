/** Image assets only. Eligibility and numerical rules come from /api/config.
 * Stage art: rcp-fe-lol-collections/global/default/perks/images/construct/{pathId}/environment.jpg
 * Pinned source manifests:
 * https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perks.json
 * https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perkstyles.json
 */
export const runeAssetVersion = "16.17";
export const runePathAssets: Record<
  string,
  { id: number; icon: string; background: string }
> = {
  Resolve: {
    id: 8400,
    icon: "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/7204_resolve.png",
    background:
      "https://raw.communitydragon.org/16.17/plugins/rcp-fe-lol-collections/global/default/perks/images/construct/8400/environment.jpg",
  },
  Domination: {
    id: 8100,
    icon: "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/7200_domination.png",
    background:
      "https://raw.communitydragon.org/16.17/plugins/rcp-fe-lol-collections/global/default/perks/images/construct/8100/environment.jpg",
  },
  Precision: {
    id: 8000,
    icon: "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/7201_precision.png",
    background:
      "https://raw.communitydragon.org/16.17/plugins/rcp-fe-lol-collections/global/default/perks/images/construct/8000/environment.jpg",
  },
  Sorcery: {
    id: 8200,
    icon: "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/7202_sorcery.png",
    background:
      "https://raw.communitydragon.org/16.17/plugins/rcp-fe-lol-collections/global/default/perks/images/construct/8200/environment.jpg",
  },
  Inspiration: {
    id: 8300,
    icon: "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/7203_whimsy.png",
    background:
      "https://raw.communitydragon.org/16.17/plugins/rcp-fe-lol-collections/global/default/perks/images/construct/8300/environment.jpg",
  },
};
export const runeIcons: Record<string, string> = {
  "Absolute Focus":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/absolutefocus/absolutefocus.png",
  "Absorb Life":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/absorblife/absorblife.png",
  Aftershock:
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/veteranaftershock/veteranaftershock.png",
  "Approach Velocity":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/approachvelocity/approachvelocity.png",
  "Arcane Comet":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/arcanecomet/arcanecomet.png",
  "Axiom Arcanist":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/nullifyingorb/axiom_arcanist.png",
  "Biscuit Delivery":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/biscuitdelivery/biscuitdelivery.png",
  "Bone Plating":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/boneplating/boneplating.png",
  "Cash Back":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/cashback/cashback2.png",
  Celerity:
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/celerity/celeritytemp.png",
  "Cheap Shot":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/cheapshot/cheapshot.png",
  Conditioning:
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/conditioning/conditioning.png",
  Conqueror:
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/conqueror/conqueror.png",
  "Cosmic Insight":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/cosmicinsight/cosmicinsight.png",
  "Coup de Grace":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/coupdegrace/coupdegrace.png",
  "Cut Down":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/cutdown/cutdown.png",
  "Dark Harvest":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/darkharvest/darkharvest.png",
  "Deathfire Touch":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/deathfiretouch/deathfire_touch_keystone.png",
  "Deep Ward":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/deepward/deepward.png",
  Demolish:
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/demolish/demolish.png",
  Electrocute:
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/electrocute/electrocute.png",
  "First Strike":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/firststrike/firststrike.png",
  "Fleet Footwork":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/fleetfootwork/fleetfootwork.png",
  "Font of Life":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/fontoflife/fontoflife.png",
  "Gathering Storm":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/gatheringstorm/gatheringstorm.png",
  "Glacial Augment":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/glacialaugment/glacialaugment.png",
  "Grasp of the Undying":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/graspoftheundying/graspoftheundying.png",
  "Grisly Mementos":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/grislymementos/grislymementos.png",
  Guardian:
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/guardian/guardian.png",
  "Hail of Blades":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/hailofblades/hailofblades.png",
  "Hextech Flashtraption":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/hextechflashtraption/hextechflashtraption.png",
  "Jack Of All Trades":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/jackofalltrades/jackofalltrades2.png",
  "Last Stand":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/laststand/laststand.png",
  "Legend: Alacrity":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/legendalacrity/legendalacrity.png",
  "Legend: Bloodline":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/legendbloodline/legendbloodline.png",
  "Legend: Haste":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/legendhaste/legendhaste.png",
  "Lethal Tempo":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/lethaltempo/lethaltempotemp.png",
  "Magical Footwear":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/magicalfootwear/magicalfootwear.png",
  "Manaflow Band":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/manaflowband/manaflowband.png",
  "Nimbus Cloak":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/nimbuscloak/6361.png",
  Overgrowth:
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/overgrowth/overgrowth.png",
  "Presence of Mind":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/presenceofmind/presenceofmind.png",
  "Press the Attack":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/presstheattack/presstheattack.png",
  "Relentless Hunter":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/relentlesshunter/relentlesshunter.png",
  Revitalize:
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/revitalize/revitalize.png",
  Scorch:
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/scorch/scorch.png",
  "Second Wind":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/secondwind/secondwind.png",
  "Shield Bash":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/mirrorshell/mirrorshell.png",
  "Sixth Sense":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/sixthsense/sixthsense.png",
  "Stormraider's Surge":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/phaserush/stormraiderssurgeruneicon2.png",
  "Sudden Impact":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/suddenimpact/suddenimpact.png",
  "Summon Aery":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/summonaery/summonaery.png",
  "Taste of Blood":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/tasteofblood/greenterror_tasteofblood.png",
  "Time Warp Tonic":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/timewarptonic/timewarptonic.png",
  Transcendence:
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/transcendence/transcendence.png",
  "Treasure Hunter":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/treasurehunter/treasurehunter.png",
  "Triple Tonic":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/perfecttiming/alchemistcabinet.png",
  Triumph:
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/triumph.png",
  "Ultimate Hunter":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/ultimatehunter/ultimatehunter.png",
  Unflinching:
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/unflinching/unflinching.png",
  "Unsealed Spellbook":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/unsealedspellbook/unsealedspellbook.png",
  Waterwalking:
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/waterwalking/waterwalking.png",
};
export const shardIcons: Record<number, string> = {
  "5011":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/statmods/statmodshealthscalingicon.png",
  "5013":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/statmods/statmodstenacityicon.png",
  "5008":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/statmods/statmodsadaptiveforceicon.png",
  "5001":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/statmods/statmodshealthplusicon.png",
  "5007":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/statmods/statmodscdrscalingicon.png",
  "5005":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/statmods/statmodsattackspeedicon.png",
  "5010":
    "https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/statmods/statmodsmovementspeedicon.png",
};
// Names from the calculator shard catalogue map to client IDs; order stays config-driven.
export const shardAssetIds: Record<string, number> = {
  "Adaptive Force": 5008,
  "Attack Speed": 5005,
  "Cooldown Reduction": 5007,
  "Movement Speed": 5010,
  "Health Scaling": 5001,
  Health: 5011,
  "Tenacity and Slow Resist": 5013,
};

/** Description source matches the calculator snapshot, separately from image assets.
 * https://raw.communitydragon.org/16.16/plugins/rcp-be-lol-game-data/global/default/v1/perks.json
 */
export const runeDescriptionVersion = "16.16";
export const runeDescriptions: Record<string, string> = {
  "Absolute Focus":
    "While above 70% health, gain an <lol-uikit-tooltipped-keyword key='LinkTooltip_Description_Adaptive'><font color='#48C4B7'>adaptive</font></lol-uikit-tooltipped-keyword> bonus of up to 18 Attack Damage or 30 Ability Power (based on level). <br><br>Grants 1.8 Attack Damage or 3 Ability Power at level 1. ",
  "Absorb Life": "Killing a target restores 1 - 23 Health based on level.",
  Aftershock:
    "After immobilizing an enemy champion, increase your Armor and Magic Resist by 45 + 75% of your Bonus Resists for 2.5s. Then explode, dealing magic damage to nearby enemies.<br><br>Damage: 25 - 120 (+8% of your bonus health)<br>Cooldown: 20s<br><br>Resistance bonus from Aftershock capped at: 80-150 (based on level)<br>",
  "Approach Velocity":
    "Gain <speed>7.5% Move Speed</speed> towards nearby enemy champions that are movement impaired. This bonus is increased to <speed>15% Move Speed</speed> for any enemy champion that you impair. <br><br>Activation Range for CC from allies: 1000",
  "Arcane Comet":
    "Damaging a champion with an ability hurls a comet at their location, dealing increased damage based on distance.<br><br><lol-uikit-tooltipped-keyword key='LinkTooltip_Description_AdaptiveDmg'><font color='#48C4B7'>Adaptive Damage</font></lol-uikit-tooltipped-keyword>: 15 - 100 based on level (<scaleAP>+0.05 AP</scaleAP> and <scaleAD>+0.1 bonus AD</scaleAD>)<br>Cooldown: 20 - 8s<br><rules><br>Damage amplification scales up to 100% at 750 range.<br></rules>",
  "Axiom Arcanist":
    "Your Ultimate has 12% increased damage, healing, and shielding. <br>(AoE damage is reduced to a 8% increase)<br><br>Scoring a takedown on an enemy champion reduces your Ultimate's current cooldown by 7%.",
  "Biscuit Delivery":
    "Biscuit Delivery: Gain a Total Biscuit of Everlasting Will every 2 mins, until 6 min.<br><br>Biscuits restore 20 + 2% of your maximum health, increased by up to 100% based on missing Health. Consuming or selling a Biscuit permanently increases your max health by 30. ",
  "Bone Plating":
    "After taking damage from an enemy champion, the next 3 spells or attacks you receive from them deal 30-60 (based on level) less damage.<br><br>Duration: 1.5s<br>Cooldown: 55s",
  "Cash Back": "Get 7.5% Gold back when you purchase Legendary Items.",
  Celerity:
    "All movement bonuses are 7% more effective on you and gain <speed>1% Move Speed</speed>.",
  "Cheap Shot":
    "Damaging champions with <b>impaired movement or actions</b> deals 10 - 45 bonus true damage (based on level).<br><br>Cooldown: 4s<br><rules>Activates on damage occurring after the impairment.</rules>",
  Conditioning:
    "After 12 min gain +8 Armor and +8 Magic Resist and increase your Armor and Magic Resist by 3%.",
  Conqueror:
    "Basic attacks or spells that deal damage to an enemy champion grant 2 stacks of Conqueror for 5s, gaining 1.8-4 <lol-uikit-tooltipped-keyword key='LinkTooltip_Description_Adaptive'><font color='#48C4B7'>Adaptive Force</font></lol-uikit-tooltipped-keyword> per stack. Stacks up to 12 times. Ranged champions gain only 1 stack per basic attack.<br><br>When fully stacked, heal for 8% of the damage you deal to champions (5% for ranged champions).",
  "Cosmic Insight":
    "+<attention>18</attention> Summoner Spell Haste<br>+<attention>10</attention> Item Haste",
  "Coup de Grace":
    "Deal 8% more damage to champions who have less than 40% health.",
  "Cut Down": "Deal 8% more damage to champions who have more than 60% health.",
  "Dark Harvest":
    "Damaging a Champion below 50% health deals <lol-uikit-tooltipped-keyword key='LinkTooltip_Description_AdaptiveDmg'>adaptive damage</lol-uikit-tooltipped-keyword> and harvests their soul, permanently increasing Dark Harvest's damage by 11.<br><br>Dark Harvest damage: 30 (+11 damage per soul) (+0.1 bonus AD) (+0.05 AP)<br>Cooldown: 35s (resets to 1.0s on takedown)",
  "Deathfire Touch":
    "Damaging a champion with an ability burns them for 3 - 12 based on level (+<scaleAP>2.5% AP</scaleAP>) (+<scaleAD>7% bonus AD</scaleAD>)  magic damage per second. After burning for 3 seconds, the damage of the burn increases by 75% while they remain on fire.<br><rules><br>Duration:<br>Single Target: 4s<br>Area of Effect: 2s<br>Damage over Time: 1s<br></rules>",
  "Deep Ward":
    "Your wards in the enemy jungle are <keywordMajor>Deep</keywordMajor>. <keywordMajor>Deep</keywordMajor> wards gain +1 extra Health and +[30 - 45]s increased duration (+[45 - 150]s for Trinket stealth wards).<br><br>Level 9: Wards in the river are also <keywordMajor>Deep</keywordMajor>.",
  Demolish:
    "Your third attack against towers deals [85 (+28% max Health) Melee || 50 (+20% max Health) Ranged] bonus physical damage.<br><br>Cooldown: 30s",
  Electrocute:
    "Hitting a champion with 3 <b>separate</b> attacks or abilities within 3s deals bonus <lol-uikit-tooltipped-keyword key='LinkTooltip_Description_AdaptiveDmg'><font color='#48C4B7'>adaptive damage</font></lol-uikit-tooltipped-keyword>.<br><br>Damage: 70 - 240 (+0.1 bonus AD, +0.05 AP) damage.<br>Cooldown: 20s<br><br><i>'We called them the Thunderlords, for to speak of their lightning was to invite disaster.'</i>",
  "First Strike":
    "Attacks or abilities against an enemy champion within 0.25s of entering champion combat grant 10 gold and <b>First Strike</b> for 3 seconds, causing you to deal <truedamage>7%</truedamage> extra <truedamage> damage</truedamage> against champions, and granting <gold>50% (35% for ranged champions)</gold> of bonus damage dealt as <gold>gold</gold>.<br><br>Cooldown: <scaleLevel>25 - 15</scaleLevel>s",
  "Fleet Footwork":
    "Attacking and moving builds Energy stacks. At 100 stacks, your next attack is Energized<br><br>Energized attacks heal you for 10 - 130 (+0.1 Bonus AD, +0.05 AP) and grant <speed>20% Move Speed</speed> for 1s.<br><br>For Ranged Champions, Healing is 60% effective and Move Speed is 75% effective. All healing is 15% effective against Minions.",
  "Font of Life":
    "Impairing the movement of an enemy champion restores Health to you and the lowest health nearby allied champion.<br><br>70% effect for Ranged Users.<br><br>Cooldown: 20s",
  "Gathering Storm":
    "Every 10 min gain AP or AD, <lol-uikit-tooltipped-keyword key='LinkTooltip_Description_Adaptive'><font color='#48C4B7'>adaptive</font></lol-uikit-tooltipped-keyword>.<br><br><i>10 min</i>: + 8 AP or 5 AD <br><i>20 min</i>: + 24 AP or 14 AD<br><i>30 min</i>: + 48 AP or 29 AD<br><i>40 min</i>: + 80 AP or 48 AD<br><i>50 min</i>: + 120 AP or 72 AD<br><i>60 min</i>: + 168 AP or 101 AD<br>etc...",
  "Glacial Augment":
    "Immobilizing an enemy champion will cause 3 glacial rays to emanate from them towards you and other nearby champions, creating frozen zones for 3 (+ the immobilizing effect's duration) seconds that slow enemies for 20% (+90% per 100% Heal and Shield Power) (+6% per 100 Ability Power) (+7% per 100 bonus Attack Damage) and reduce their damage by 15% against your allies (not including yourself). <br><br>Cooldown: 25s",
  "Grasp of the Undying":
    "Every 4s in combat, your next basic attack on a champion will:<li>Deal bonus magic damage equal to 3.5% of your max health<li>Heal you for 1.3% of your max health<li>Permanently increase your health by 5<br><rules><i>Ranged Champions:</i> Damage, healing, and permanent health gained are 40% effective.</rules>",
  "Grisly Mementos":
    "Collect 1 memento on champion <lol-uikit-tooltipped-keyword key='LinkTooltip_Description_Takedown'>takedowns</lol-uikit-tooltipped-keyword>, up to 18 total.<br><br>Gain 6 Trinket Haste for each collected. In game modes where vision Trinkets do not exist, instead gain 3 Summoner Spell Haste.",
  Guardian:
    "<i>Guard</i> allies within 350 units of you, and allies you target with spells for 2.5s. While <i>Guarding</i>, if you or the ally take more than a small amount of damage over the duration of the <i>Guard</i>, both of you gain a shield for 1.5s.<br><br>Cooldown: <scaleLevel>75 - 40</scaleLevel> seconds<br>Shield: <scaleLevel>40 - 150</scaleLevel> + <scaleAP>20%</scaleAP> of your ability power + <scalehealth>6%</scalehealth> of your bonus health<br>Proc Threshold: <scaleLevel>50 - 165</scaleLevel> postmitigation damage",
  "Hail of Blades":
    "Gain 90% (60% for ranged champions) Attack Speed and <trueDamage>bonus true damage</trueDamage> when you attack an enemy champion for up to 3 attacks.<br><br>No more than 3s can elapse between attacks or this effect will end.<br><br>Cooldown: 10s.<br>On-Hit Damage: 2 - 20 (+0.12 bonus AD, +0.1 AP) damage.<br><br><rules>Attack resets increase the attack limit by 1.<br>Allows you to temporarily exceed the Attack Speed limit.</rules>",
  "Hextech Flashtraption":
    "While Flash is on cooldown it is replaced by <i>Hexflash</i>.<br><br><i>Hexflash</i>: Channel for 2s to blink to a new location.<br><br>Cooldown: 20s. Goes on a 10s cooldown when you enter champion combat.",
  "Jack Of All Trades":
    "For each different stat gained from items, gain one Jack stack. Each stack grants you <speed>1 Ability Haste</speed>.<br><br>Gain 8 or 20 bonus <lol-uikit-tooltipped-keyword key='LinkTooltip_Description_Adaptive'>Adaptive Force</lol-uikit-tooltipped-keyword> at 5 and 10 stacks, respectively.",
  "Last Stand":
    "Deal 5% - 11% increased damage to champions while you are below 60% health. Max damage gained at 30% health.",
  "Legend: Alacrity":
    "Gain 3% attack speed plus an additional 1.5% for every <i>Legend</i> stack (<statGood>max 10 stacks</statGood>).<br><br>Earn progress toward <i>Legend</i> stacks for every champion takedown, epic monster takedown, large monster kill, and minion kill.",
  "Legend: Bloodline":
    "Gain <scaleAD>0.45% Life Steal</scaleAD> for every <i>Legend</i> stack (<statGood>max 15 stacks</statGood>). At maximum <i>Legend</i> stacks, gain <scaleHealth>85 max health</scaleHealth>.<br><br>Earn progress toward <i>Legend</i> stacks for every champion takedown, epic monster takedown, large monster kill, and minion kill.",
  "Legend: Haste":
    "Gain 1.5 basic ability haste for every <i>Legend</i> stack (<statGood>max 10 stacks</statGood>).<br><br>Earn progress toward <i>Legend</i> stacks for every champion takedown, epic monster takedown, large monster kill, and minion kill.",
  "Lethal Tempo":
    "Attacking an enemy champion grants you [6% Melee || 4% Ranged] Attack Speed for 6 seconds, up to 6. At max stacks, deal [9 - 30 Melee || 6 - 24 Ranged] <lol-uikit-tooltipped-keyword key='LinkTooltip_Description_AdaptiveDmg'>bonus adaptive damage On-Attack, increased by 1% per 1% Bonus Attack Speed</lol-uikit-tooltipped-keyword>.",
  "Magical Footwear":
    "You get free Slightly Magical Footwear at 12 min, but you cannot buy boots before then. For each takedown you acquire the boots 45s sooner.<br><br>Slightly Magical Footwear grants you an additional <speed>10 Move Speed</speed>.",
  "Manaflow Band":
    "Hitting an enemy champion with an ability permanently increases your maximum mana by 25, up to 250 mana.<br><br>After reaching 250 bonus mana, restore 1% of your missing mana every 5 seconds.<br><br>Cooldown: 15 seconds",
  "Nimbus Cloak":
    "After casting a Summoner Spell, gain a <speed>Move Speed</speed> increase that lasts for 2s and allows you to pass through units.<br><br>Increase: <speed>15% - 45% Move Speed</speed> based on the Summoner Spell's cooldown. (Higher cooldown Summoner Spells grant more <speed>Move Speed</speed>). ",
  Overgrowth:
    "Absorb life essence from monsters or enemy minions that die near you, permanently gaining 3 maximum health for every 8.<br><br>When you've absorbed 120 monsters or enemy minions, gain an additional 3.5% maximum health.",
  "Presence of Mind":
    "Damaging an enemy champion restores 6-50 (80% for ranged) mana or 6 energy.<br><br>Takedowns restore 15% of your maximum mana or energy. <br><br>Cooldown for damage restoration: 8s",
  "Press the Attack":
    "Hitting an enemy champion with 3 consecutive basic attacks deals 40 - 160 bonus <lol-uikit-tooltipped-keyword key='LinkTooltip_Description_AdaptiveDmg'><font color='#48C4B7'>adaptive damage</font></lol-uikit-tooltipped-keyword> (based on level) and amplifies your damage dealt by 8% until you leave combat with champions.",
  "Relentless Hunter":
    "Gain <speed>8 Move Speed</speed> out of combat per <i>Bounty Hunter</i> stack. <i>Bounty Hunter</i> stacks are earned the first time you get a takedown on each enemy champion.",
  Revitalize:
    "Gain 5% Heal and Shield Power.<br><br>Heals and shields you cast or receive are 10% stronger on targets below 40% health.",
  Scorch:
    "Your next damaging ability hit sets champions on fire dealing 20 - 40 bonus magic damage based on level after 1s.<br><br>Cooldown: 10s",
  "Second Wind":
    "After taking damage from an enemy champion, heal for 4% of your missing health over 10s.",
  "Shield Bash":
    "Whenever you gain a new shield,  your next basic attack against a champion deals <scaleLevel>5 - 30</scaleLevel> <scaleHealth>(+2.5% Bonus Health)</scaleHealth> <scaleMana>(+15.0% New Shield Amount)</scaleMana> bonus <lol-uikit-tooltipped-keyword key='LinkTooltip_Description_Adaptive'><font color='#48C4B7'>adaptive</font></lol-uikit-tooltipped-keyword> damage.<br><br>You have up to 2s after the shield expires to use this effect.",
  "Sixth Sense":
    "Automatically sense a nearby untracked and unseen ward, tracking it for the team. <br><br>Level 11: Also reveal the ward for 10s.<br><br>This effect has a 250 second Cooldown.",
  "Stormraider's Surge":
    "Dealing 25% of a champion's maximum health within 3s grants <speed>48% Move Speed</speed> and <status>50% Slow Resistance</status> for 4s. Move Speed is 75% effective for ranged champions.<br>Cooldown: 20s - 10s",
  "Sudden Impact":
    "Damaging basic attacks and abilities deal a bonus <trueDamage>20 - 80 True Damage</trueDamage> based on level to enemy champions after using a dash, leap, blink, teleport, or when leaving stealth for 4s.<br><br>Cooldown: 10s",
  "Summon Aery":
    "Damaging enemy champions with basic attacks or abilities sends Aery to them, dealing 10 - 50 based on level (+<scaleAP>0.05 AP</scaleAP>) (+<scaleAD>0.1 bonus AD</scaleAD>).<br><br>Empowering or protecting allies with abilities sends Aery to them, shielding them for 20 - 100 based on level (+<scaleAP>0.05 AP</scaleAP>) (+<scaleAD>0.1 bonus AD</scaleAD>).<br><br>Aery cannot be sent out again until she returns to you.",
  "Taste of Blood":
    "Heal when you damage an enemy champion.<br><br>Healing: 16-40 (+0.1 bonus AD, +0.05 AP) health (based on level)<br><br>Cooldown: 20s",
  "Time Warp Tonic":
    "Consuming a potion grants 40% of its health restoration immediately.",
  Transcendence:
    "Gain bonuses upon reaching the following levels:<br>Level 5: +5 <lol-uikit-tooltipped-keyword key='LinkTooltip_Description_CDR'>Ability Haste</lol-uikit-tooltipped-keyword> <br>Level 8: +5 <lol-uikit-tooltipped-keyword key='LinkTooltip_Description_CDR'>Ability Haste</lol-uikit-tooltipped-keyword> <br>Level 11: On Champion takedown, reduce the remaining cooldown of basic abilities by 20%.",
  "Treasure Hunter":
    "Gain an additional <gold>50 gold</gold> the next time you collect a <i>Bounty Hunter</i> stack. Increase the gold gained by <gold>20 gold</gold> for each <i>Bounty Hunter</i> stack, up to <gold>130 gold</gold>.<br><br><i>Bounty Hunter</i> stacks are earned the first time you get a takedown on each enemy champion.",
  "Triple Tonic":
    "Upon reaching level 3, gain an Elixir of Avarice.<br>Upon reaching level 6, gain an Elixir of Force.<br>Upon reaching level 9, gain an Elixir of Skill. ",
  Triumph:
    "Takedowns restore 5% of your missing health, 2.5% of your max health, and grant an additional 20 gold. <br><br><hr><br><i>'The most dangerous game brings the greatest glory.' <br>\u2014Noxian Reckoner</i>",
  "Ultimate Hunter":
    "Your ultimate gains <attention>6</attention> Ability Haste, plus an additional <attention>5</attention> Ability Haste per <i>Bounty Hunter</i> stack. <i>Bounty Hunter</i> stacks are earned the first time you get a takedown on each enemy champion.",
  Unflinching:
    "Gain 10 Armor and Magic Resist when crowd controlled and for 2 seconds after.",
  "Unsealed Spellbook":
    "Swap one of your equipped Summoner Spells to a new, single use Summoner Spell. Each unique Summoner Spell you swap to permanently decreases your swap cooldown by 25s (initial swap cooldown unavailable in the source text). <br><br>Your first swap becomes available at 6 mins. <br><rules><br>Summoner Spells can only be swapped while out of combat. <br>After using a swapped Summoner Spell you must swap 3 more times before the first can be selected again.<br>Smite damage increases after two Summoner Spell swaps. </rules>",
  Waterwalking:
    "Gain <speed>10 Move Speed</speed> and <lol-uikit-tooltipped-keyword key='LinkTooltip_Description_Adaptive'><font color='#48C4B7'>13 - 30 Adaptive Force</font></lol-uikit-tooltipped-keyword> (based on level) when in the river.<br><br><i>May you be as swift as the rushing river and agile as a startled Rift Scuttler.</i>",
};
export const shardDescriptions: Record<number, string> = {
  "5011": "+65 Health",
  "5013": "+15% Tenacity and Slow Resist",
  "5008":
    "+9 <lol-uikit-tooltipped-keyword key='LinkTooltip_Description_Adaptive'><font color='#48C4B7'>Adaptive Force</font></lol-uikit-tooltipped-keyword>",
  "5001": "+10-180 Health (based on level)",
  "5007":
    "+8 <lol-uikit-tooltipped-keyword key='LinkTooltip_Description_CDR'>Ability Haste</lol-uikit-tooltipped-keyword> ",
  "5005": "+10% Attack Speed",
  "5010":
    "+2.5% <lol-uikit-tooltipped-keyword key='LinkTooltip_Description_MS'>Move Speed</lol-uikit-tooltipped-keyword>",
};

export const runePathDescriptions: Record<string, string> = {
  Resolve: "Durability and crowd control",
  Domination: "Burst damage and target access ",
  Precision: "Improved attacks and sustained damage",
  Sorcery: "Empowered abilities and resource manipulation",
  Inspiration: "Creative tools and rule bending ",
};
