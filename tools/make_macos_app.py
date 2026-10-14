"""Create a local Finder app after setting up .venv-macos (macOS only)."""
import pathlib
import plistlib
import shutil
import subprocess
import sys


def main():
    if sys.platform != "darwin":
        raise SystemExit("This launcher is for macOS.")
    kit = pathlib.Path(__file__).resolve().parents[1]
    if not (kit / ".venv-macos/bin/python").is_file():
        raise SystemExit("Set up .venv-macos first; see docs/MACOS.md.")
    compiler = shutil.which("clang")
    if not compiler:
        raise SystemExit("clang is required to build the Finder launcher. Use Start D5 Mod Kit.command instead.")
    app = kit / "D5 Mod Kit.app"
    if app.exists():
        raise SystemExit(f"{app} already exists; remove your generated launcher before rebuilding it.")
    (app / "Contents/MacOS").mkdir(parents=True)
    try:
        subprocess.run([compiler, "-O2", "-Wall", "-Wextra", "-Werror", "-o",
                        str(app / "Contents/MacOS/launch"), str(kit / "tools/macos_launcher.c")], check=True)
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
            "CFBundleExecutable": "launch", "CFBundleIdentifier": "org.d5modkit.macos",
            "CFBundleName": "D5 Mod Kit", "CFBundlePackageType": "APPL", "CFBundleVersion": "1.3",
            "NSHighResolutionCapable": True,
        }))
    except Exception:
        shutil.rmtree(app)
        raise
    print(app)


if __name__ == "__main__":
    main()
