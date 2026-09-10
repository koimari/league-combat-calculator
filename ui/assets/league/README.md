# League interface source assets

These files come from the CommunityDragon export for patch **16.17**. `source-manifest.json` records each source URL, SHA-256, byte length, and image dimensions. This folder contains a bounded set of HUD textures, rune backgrounds, and layout evidence.

## HUD geometry

`playerframe-layout.json` and `playerinventory-layout.json` are Riot UIBase property exports. Each element supplies `Position.UIRect.Position`, `Size`, the source resolution, its anchor, and layer order. `TextureData.mTextureUV` gives pixel bounds `[left, top, right, bottom]` within the named atlas. The HUD elements use a 1600 by 1200 source resolution and a bottom-center anchor `[0.5, 1]`.

| Element | Atlas | UV bounds | Render size | Source position |
| --- | --- | --- | --- | --- |
| HUDCenterFrame | clarity_hudatlas.png | 192,647,772,833 | 580×186 | 415,1022 |
| PortraitFrame | clarity_hudatlas.png | 9,659,183,839 | 174×180 | 312,1032 |
| PortraitFrameUnderlay | clarity_hudatlas.png | 803,794,943,934 | 140×140 | 326,1041 |
| Ability0_BorderAvailable | clarity_hudatlas.png | 545,266,615,336 | 66×66 | 544,1053 |
| PlayerHP_BarTextureGreen | clarity_hudatlas.png | 2,920,461,938 | 461×18 | 491,1144 |
| PlayerPar_BarTextureBlue | clarity_hudatlas.png | 2,942,461,960 | 461×18 | 491,1166 |
| InventoryFrame | clarity_hudatlasupdate.png | 9,416,259,586 | 258×178 | 973,1030 |

`PlayerIcon_Base` places the champion portrait at 335,1050 with a size of 124×124. The game supplies its champion texture at runtime. Sprite dimensions can differ from render dimensions; preserve that scaling when drawing the atlas region.

These descriptors allow the web component to use the original frame art and measured geometry. Animated effects and game shaders require separate rendering work. The selected user screenshot can also use a different HUD scale or patch, so compare the rendered result with that reference before calling it an exact match.

## Rune editor

`rune-environment-{style}.jpg` contains the plain stage for each tree. All five are 1162×720. Style IDs are Precision 8000, Domination 8100, Sorcery 8200, Inspiration 8300, and Resolve 8400. The client adds separate construct and keystone layers above these environments. `rune-keystone-border.svg` contains the original selection border.

`client-collections.css` is the exact client CSS export retained as research evidence. Read its selector geometry and colors when building isolated application styles. It contains unrelated collection styles and client-only asset paths.

Use the patch-specific [perk data](https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perks.json) for names and `iconPath`. The [style data](https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/v1/perkstyles.json) defines tree IDs, rows, and shard order. Map `/lol-game-data/assets/<path>` to `https://raw.communitydragon.org/16.17/plugins/rcp-be-lol-game-data/global/default/<lowercase-path>`, as described in the [CommunityDragon asset documentation](https://communitydragon.org/documentation/assets).

The `assetMap` merged backgrounds in perkstyles include the central rune symbol. The separate environment images in this folder support the plain city and landscape view used by the editor.

## Serving

The standalone build can copy only PNG, JPG, and SVG assets to `static/calculator/league/`. Scryglass can copy them to `public/calculator/league/`. Keep the manifest and layout/CSS evidence in the source folder. Components can instead use the exact versioned remote URLs from the manifest when their host permits them.

The assets are owned by Riot Games. CommunityDragon exports them under Riot's [Legal Jibber Jabber policy](https://www.riotgames.com/en/legal).
