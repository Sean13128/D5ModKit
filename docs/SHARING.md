# Sharing mods with other players

The kit can turn your mods into **one installer .exe**. Players run it, click Install, and play: they need no
Python, no kit and no setup. The same file uninstalls the mods again and leaves every game file exactly as it was.

## Making a package (you, with the kit)

    python tools/export_pack.py "My D5 Mods.exe" --title "My Disgaea 5 mods"
    python tools/export_pack.py Outfits.exe --title "DRPG outfits" --mods Outfit_System,DRPG_Outfits_Etna,DRPG_Human_Usalia
    python tools/export_pack.py Pack.exe --title "..." --desc-file notes.txt

* `--mods`: the mods to put in the package, comma-separated mod folder names. The default is your enabled mods, in
  load order. Required mods must be included: Outfit_System for anything with outfits or new characters.
* `--desc` / `--desc-file`: the text the installer shows. Without it, the installer lists the mods and their
  descriptions.
* Close the game first. The export installs exactly the chosen mods into your game, so it needs a clean
  Steam *Disgaea 5 Complete* (PC) install underneath the kit's install. It then records how each changed file differs
  from vanilla and rebuilds every file from the package to check it before writing the exe.
* If `--mods` differs from your enabled set, your usual mods are installed again afterwards
  (`--keep-installed` skips that).
* It takes about 2 minutes. All 33 current mods make a ~405 MB exe, mostly the outfit sprites. A few mods make a few MB.

## Installing (players)

1. Close Disgaea 5.
2. Run the .exe. It finds the game through Steam (all Steam library folders), or you choose the folder.
3. Click **Install**: a few seconds. Start the game as usual.

**Uninstall** in the same window puts the original files back, byte for byte. Installing another package first
removes the mods of the one installed before.

Command line (for scripts, launchers, mod managers):

    "My D5 Mods.exe" /install "D:\Games\Disgaea 5 Complete" /quiet
    "My D5 Mods.exe" /uninstall "D:\Games\Disgaea 5 Complete" /quiet

## What the installer does, and what it refuses

* Before writing anything, it checks every file it will change: size, and SHA-1 of the part the package relies on.
  * A different game build, or a game already modified by the kit or by other tools, is refused ("not the game
    version this package was made for"), and nothing is changed.
  * To fix that, restore the vanilla files first: the kit's Restore vanilla, the other package's Uninstall, or
    Steam's *Verify integrity of game files*.
* Backups of the original files go to `<game>\D5Mods\backup`, and the install record to `<game>\D5Mods\installed.txt`.
  Uninstall uses them and then removes the folder.
* Big archives aren't copied whole. The package holds the new header plus instructions: copy this range from your own
  vanilla file, insert these new bytes. That is why a package is a fraction of the size of the files it produces.
* Saves are never touched.
  * A save that contains units the mods add (new characters, outfits worn) expects those mods to be installed.
  * Keep a copy of your saves before playing with such mods, and before uninstalling them.
* A Steam update or *Verify integrity* replaces the modded files with vanilla ones. Run the installer again afterwards.
* If the game is under `C:\Program Files`, Windows may require *Run as administrator* (the installer says so when it
  cannot write).

## Sharing mods with other kit users (`d5lib/modshare.py`)

Home › right-click a mod › **Share (export as .zip)…** (Characters page: **📤 Share this character…**); the other
person uses Home › More › **Import / update from .zip…**.

* The zip is the mod's folder. Its `mod.json` carries `uid` (the mod's identity on every PC, made on its first
  export), `version`, `author` and `based_on` (the mods it was made from: **Make my own version…** copies a mod
  under a new uid and appends the original there).
* **Update**: importing a package whose uid is installed replaces that mod (its folder is kept as a zip in
  `state/mod_backups/`) and keeps whether it is switched on.
* **Clashing ids** are moved, never another mod's: unique class ids (new characters, outfit slots, a filled-in
  "DLC Dummy" row becomes a row of its own), new sprite numbers (groups of ten; files renamed, blocks inside
  renumbered), charhelp ids, quest ids and progress slots, magic.dat / Skill.dat ids, custom choreography blocks and
  effect ids. The move is stored in the imported `mod.json` (`local_ids`), and every later update of the same uid is
  moved the same way, so units in saves (their class, skills, evilities, quest progress) stay valid.
* New generic class families are not moved: when one clashes the import stops and says which.
* Rows of the game a mod edits (by index) are the same on every PC and are not moved; two mods editing the same
  row simply layer in load order.

## Sharing the whole kit (for other modders)

    python tools/make_release.py D:\Release --zip

* Profiles: `--profile outfits` (default: the Outfit System and the outfit mods) or `--profile all`; `--mods A,B`
  adds mods by folder name (and stops when a mod's requirement is missing).
* The Item World auto-battle never goes in (it stays on this PC): its mod, page, docs, Python modules and native
  sources are left out, and the runtime DLL is compiled from the release's own sources without it
  (`d5noauto.inc.c` stands in; `d5lib/runtime.py`). The stand-in keeps what the auto-battle's tick did for
  everyone: the link's injected keys, the screen-state and screen-text hooks (custom colour slots find the colour
  editor by its text). Verified in game 2026-10-11 by swapping it into the running game: link, keys, texts, custom
  colours and per-look outfit colours work; `auto on` answers "this runtime has no auto-battle".
* The guide and README are written for what the release holds: `<!--mod:ID,ID-->…<!--/mod-->` blocks and lines
  ending in `<!--mod-line:ID-->` stay only when one of those mods is in; `<!--full-->…<!--/full-->` is this PC's
  copy only; `<!--share: TEXT -->` shows only in a release (`{OUTFIT_SUMMARY}` = "N outfits for M characters").
* What it makes: `D:\Release\D5ModKit` and `D:\Release\D5ModKit.zip` (about 1.6 GB). They contain:
  * the kit and the profile's mods;
  * `runtime\`: a private Python 3.10 with every library the kit uses (PyQt6, numpy, scipy, Pillow, pefile,
    keystone, capstone, pip);
  * the compiled runtime DLLs;
  * the Disgaea RPG sprites, faces and cut-ins the builders read;
  * `START HERE - Guide.html`, `Start D5 Mod Kit.bat` and `D5 Mod Kit Console.bat`.
* For the other person: extract it (best into the game folder), double-click `Start D5 Mod Kit.bat`, press
  Install & Play. Nothing to install. The kit finds the game through Steam if it is elsewhere, or asks for it.
* Never in the zip:
  * `state\` (your backups of your own game files) and `settings.json` (your game folder);
  * `cache\` (rebuilt from the other person's game);
  * `_research\` and `_extracted\`.
* Verified: a copy running on its own Python installs byte-identical game files to the original kit, and its restore
  gives back the original files exactly.

## For kit developers

* `d5lib/package.py`: export, payload format (manifest, ops), `verify_against` (rebuild check).
* `d5lib/native_tools/d5pack_installer.c`: the installer stub (Win32, no runtime dependencies). It is built with Zig
  into `d5lib/bin/d5pack_installer.exe`; the build command is at the top of the file.
* Install speed in the kit itself (2026-10-09): about 1 minute for everything. Before, it took 28 minutes.
  * The native LZS codec is `d5lib/bin/d5lzs.dll`, built from `d5lib/native_tools/lzs.c` with
    `python -m ziglang cc` when it is missing or older than the source.
  * The pure-Python codec is the fallback, so the kit still works without it.
