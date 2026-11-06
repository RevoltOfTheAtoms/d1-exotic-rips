# Destiny 1 (PS4) data formats

What the code relies on, verified against the CUSA00568 disc (v1.01) and the final patch (v1.33). Tag ids are
hexadecimal. "1.01 index" names an investment table by its entry number in `investment_globals_012c` on the disc.

## Packages (`d1kit/pkg/`)

- Bungie **Tiger** engine, PS4 flavour: little-endian header, `version == 24`, `platform == 7`. Same layout as
  [tiger-pkg](https://github.com/v4nguard/tiger-pkg)'s `d1_roi` (`src/d1_roi/structs.rs`), not `d1_ttk` (big-endian
  PS3/X360).
- Header: entry table @0xB4 (count, offset), block table @0xD0, named-tag table @0xEC. Blocks are 0x40000 bytes.
- Block flag `0x1` = Oodle compressed. Compressed blocks start `0xB7`: the **legacy (pre-Kraken) Oodle** codec. Only
  `oo2core_3` decodes it (`oo2core_9` returns 0). No encryption in D1 blocks.
- Patches: each package has numbered patch files (`_0` on the disc, `_1`... in the patch). The newest file's entry table
  wins; its blocks may live in any older patch file or on the disc (`Package` follows the block's patch id).
- **Tag** = `0x80800000 + (pkg_id << 13) + entry index` (`d1kit/pkg/tags.py`). Entry types: `16/0` tag structs,
  `32/x` headers whose `reference` field points at the `1/x` data entry (textures, buffers).

## Items and gear art (`d1kit/game/gear.py`, `d1kit/game/items.py`)

- Item definitions: class `80801806` (1.33: in `0131`/`0132`). Item hash @0x40 (1.01) / @0x78 (1.33). At
  hash+0x10 the equip slot (2/3/4 = primary/special/heavy), at +0x12 the tier (5 = Exotic).
- **Gear art**: table #96 (`808016fe`) lists one item hash per arrangement index. Use it, not the manifest's
  `gearArtArrangementIndex` (shifted by later content). Raid "(Adept)" and "((NAME~))" items have no entry and use
  the same-named weapon's (`gear.shared_raid_art`).
- Arrangements: table #40 (`808034d7`): per index, gear slots -> lists of part asset hashes (variants). 1.33 slot lists
  hold u64 relative pointers to shared slot records; `store.table()` re-bases the 1.33 tables to the 1.01 layout.
- Asset hash -> tag: sorted pairs in `0135 #1` (`80800341`; 1.33 adds class `80803aaa` in `investment_assets_013f`)
  -> type-128 stub -> entity `80800734`.
- Entity -> mesh tag `80801ab5` and plate set `80801c3c`.

## Meshes (`d1kit/export/mesh.py`)

- Mesh records (0xA0 stride): position scale/offset, UV scale/offset, vertex buffers, index buffer, parts (0x24 stride).
- VB0 = int16x4 position. Two layouts: VB0 stride 8 (position only) with VB1 = int16 UV, normal, tangent (+4 bytes);
  or VB0 stride 12 (position + UV, later content) with VB1 = normal, tangent (+4).
- Index buffers are u16 triangle strips with `0xFFFF` restart.
- Part record: keep parts with `lod & 1`. Material `80aae10b`/`80aae10c` = depth/shadow duplicates (skipped).
- Part flags: `0x20` effect pass (glows, smoke, holo reticles, sword energy), `0x40` decal, `0x300` lens/screen on a
  runtime render target, `0x10` sword hilt crystal. Byte 2 (`flags >> 16 & 0xFF`) is the **change colour index**:
  dye slot = cci // 2, odd = secondary colour. Confirmed against Bungie's web gear data.
- Coordinates are Z-up metres; exported Y-up.

## Plates and textures (`d1kit/export/canvas.py`, `d1kit/textures/`)

- Plate sets list plates `80800147`: `slot = canvas << 16 | channel`, texture, x, y, w, h. Channels: 0 diffuse (BC1,
  sRGB), 1 normal (BC5, DirectX), 2 gearstack (BC1: R dye mask, G smoothness, B metal).
- Texture headers: GNM T# descriptor + a `beefcafe` tail (`texinfo.py`). Gear plates are stored **linear** (mip 0
  first); everything else is **1D-thin tiled**. Size alone can't tell them apart when dimensions are multiples of 8.
- Mip m is `(w >> m) x (h >> m)` pixels rounded up to whole blocks.

## Materials and shaders (`d1kit/export/materials.py`, `d1kit/gpu/`)

- Material `80801ad7`: VS (`32/9`) and PS (`32/8`) GCN binaries, texture slots, samplers (`80801a42`), float4 constant
  arrays (class `80800090`; vertex constants first when present, pixel constants last).
- `t32/s7` texture entries are 16-byte stubs, not bound in the shader's texture table.
- Shaders are AMD GCN gfx7 ("Sea Islands", PS4 Liverpool) code. `gcn_dis.py` disassembles, `gcn_emu.py` runs pixel
  shaders on the CPU over N pixels at once.
- Shader resources: user-data `s[4:11]` = the material's first texture; `s[2:3]` 8-dword loads = further textures;
  constant buffers by `s_buffer_load` offset (the lowest pointer is the material's, others per-frame/view).
- **Gear dye block**: every gear shader reads a 14-slot block of runtime dye values. Its end (the dye colour slot) is
  `0x3c` past the final colour multiplier, the shader's second `0x...4`-offset load (`shader_bake.dye_block_end`). It
  is usually the material's last slot, but not always (Touch of Malice's `80a787d3` has 3 slots after it).
- Gear shader families (`materials.SHINE_FAMILY`): A `80a3d145`/`80a3c693` (most guns), B `80a38a95` (Gjallarhorn),
  C `80a39b99` (swords). Each adds an environment-cube reflection into the colour it writes.
- Glow passes (`materials.GLOW_PS`): `80aad077` = texture.rgb x texture.a x c2.rgb x c3.x; `80aadb76` =
  c3.rgb x c2.rgb x c2.w x c4.x. A stored 0 strength means the game sets it at runtime.
- G-buffer output: `mrt0` = colour, `mrt1` = normal x (0.375 + 0.125 x gloss) + 0.5, `.w` = BRDF row parameter.

## Dyes (`d1kit/game/dyes.py`)

- Per item: item definition array (class `808018ea` on 1.01, `8080101c` on 1.33) of (u16 channel, u16 dye index) ->
  table #99 -> asset hash in #41 -> asset lookup -> dye tag `80801af4`: slot @0x10, detail diffuse/normal @0x60,
  detail transform @0x70, primary @0x90, secondary @0xa0.
- The fallback blend (where a shader can't be emulated) follows Bungie's D1 web shader: overlay detail, then
  mix(diffuse, overlay(diffuse, colour), gearstack.R).

## Display data

- Names, descriptions and lore are **not** in the game files (all packages and the eboot scanned in several text
  encodings): the game downloads them from Bungie. They come from Bungie's final D1 manifest.
- Stats: raw investment stats in the item definition (array class `8080190c`); stat index -> hash via #92; display
  curves in #35. Icons: perk -> #101 -> #44 -> display tag -> texture; item -> #81 -> #26 -> stub -> texture.
- Talent grids: #94 -> class `80801963`; node steps list perks as u16 indices into the perk list (#101).
