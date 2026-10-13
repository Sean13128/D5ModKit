@echo off
rem A command prompt for the kit's command-line tools (python = the kit's own Python).
cd /d "%~dp0"
if exist "runtime\python.exe" set "PATH=%~dp0runtime;%PATH%"
title D5 Mod Kit console
echo.
echo  D5 Mod Kit command line.  Examples (see the guide, "Command-line tools"):
echo.
echo    python tools\install_mods.py                       install the enabled mods
echo    python tools\drpg_outfits.py build 10              build Killia's Disgaea RPG outfits
echo    python tools\export_pack.py Pack.exe --title "My mods"   make a player installer
echo    python tools\new_drpg_class.py --help              new class from a Disgaea RPG unit
echo.
cmd /k
