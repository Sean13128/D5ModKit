# Running the editor on macOS

The editor can run natively on macOS. The game still runs through the Windows
compatibility environment configured in Steam (tested with NotProton/CrossOver).
Place the kit next to `disgaea5.exe` or select the game folder on Home.

From a source checkout or extracted release, use Python 3.10+:

```sh
python3 -m venv .venv-macos
.venv-macos/bin/python -m pip install -r requirements.txt
# Needed when rebuilding the Windows runtime DLLs from a source checkout:
.venv-macos/bin/python -m pip install ziglang
```

Release zips may omit `requirements.txt`; install `PyQt6 numpy scipy Pillow
pefile keystone-engine capstone` in that environment instead. Start with
`Start D5 Mod Kit.command`. For a Finder app, run:

```sh
.venv-macos/bin/python tools/make_macos_app.py
```

The Finder app must stay inside the kit; a Desktop alias can point to it.
The native LZS codec builds with the local `clang`/`cc`, or Zig when no local
compiler is found, and loads a host library. The bundled Windows DLL is retained.
If building/loading fails, the existing Python codec remains available.

Play opens Steam app 803600 using the configured protocol handler. Process
checks recognize the Windows executable under Wine, excluding launch helpers.
Installation refuses when the process check fails rather than assuming the game
is closed. Per-member preparation messages keep archive work visible.

Shared saves stay managed by Steam/Wine. Separate profile saves require `APPDATA`
to point to the actual Windows Roaming directory in the selected Wine prefix.
An unconfigured separate profile is rejected before game files are written.

Validation: native/Python codec cross-decoding with synthetic data, Mac routing
and preflight unit tests. On Apple Silicon, real release sprites compressed
approximately 40–50 times faster than the Python fallback; this is a codec
benchmark, not a measured full-install speedup. Windows/Linux branches are
preserved but have not been run on those hosts in this change.
