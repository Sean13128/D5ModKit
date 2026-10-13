@echo off
rem Starts the D5 Mod Kit with its own Python (runtime folder); falls back to an installed Python.
cd /d "%~dp0"
if exist "runtime\pythonw.exe" (
    start "" "runtime\pythonw.exe" -s -E D5ModKit.pyw
) else (
    start "" pythonw D5ModKit.pyw
)
