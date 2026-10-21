# URAH_koh2_shared

Code the URAH mods for **Knights of Honor II: Sovereign** share. Each mod repo includes this repo
as the git submodule `external/URAH_shared`.

- `URAH.Plugin.props`: common build settings of the BepInEx 5 plugins (net472, references to the
  game's and BepInEx's assemblies in your local install, never copied). A plugin's csproj imports it;
  `GameDir` points at the game folder (default: Steam on Linux).
- `ModLink.cs`: ties a plugin's Harmony patches to the game's mod list. The patches are applied while
  an active mod names the plugin's GUID in `bepinex_plugins.txt` in its root folder, and removed when
  the last such mod is switched off. Compiled into the plugins that set `URAHModLink=true`.
  In multiplayer every active link publishes its plugin version as the player var `urah_p_<guid>`
  and blocks the host's start (`client_version_mismatch`) while a player online lacks that version.
- `python/`: helpers for the tools that build map data
  - `koh2map.py`: the game's map files (realms.bin, realms.def, border and bounds data, ...)
  - `koh2terrain.py`: europe terrain constants, DEM reading
  - `koh2coa.py`: coat of arms atlases
  - `dt.py`: a reader for the game's def files
  - `extract_bundle_assets.py`: textures out of the game's asset bundles
  - `realms_inspect.py`: realm map to images and back

Only code that does not patch the game lives here: Harmony patches shared by several mods belong in a
plugin of their own (two plugins with the same patches compiled in would patch twice).
