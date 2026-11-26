#!/usr/bin/env python3
"""OLHANDOFF: build one payload for each arbitration configuration and run the yield gate on it.

Reuses the project's payload builder (integration/build_payload-158.py) unchanged, on the pinned
vanilla exe, with two differences:

  * the evility section is built with the five OLEFFECTS families (steal_on_kill_percent,
    sp_drain_per_turn, block_overload, power, defense_power, range) so the contested effect sites are
    really patched -- the project script's three sample families would leave them vanilla and prove
    nothing;
  * `d5lib.overlord_compat.ACTIVE` is set to the configuration under test *before* any section is
    built, so filter_hooks sees it exactly as an install with those mods would.

    python build_yield_payload.py <out-dir> <content|runtime|runtime+plugins>

Writes <out-dir>/payload-<config>.exe, .json (the project report) and the yield receipt.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

WT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WT))
import os
os.environ.setdefault("D5_KIT", str(WT))

from d5lib import overlord_compat  # noqa: E402

CONFIGS = {
    "content": {"runtime": False, "plugins": False, "mods": [], "families": None},
    "runtime": {"runtime": True, "plugins": False, "mods": ["Overlord Edition"], "families": None},
    "runtime+plugins": {"runtime": True, "plugins": True, "mods": ["Overlord Edition (c06c)"], "families": None},
}

FX = {
    7002: {"family": "potency", "effects": [{"stat": "atk", "value": 30}]},
    7003: {"family": "dealt", "effects": [{"value": 20, "per": "adjacent_ally"}]},
    7004: {"family": "conversion", "effects": [{"stat": "atk", "from": "sp_current", "value": 10}]},
    # the OLEFFECTS families that own contested sites
    7100: {"family": "steal_on_kill_percent", "effects": [{"value": 15}]},
    7101: {"family": "sp_drain_per_turn", "effects": [{"value": 8}]},
    7102: {"family": "block_overload"},
    7103: {"family": "power", "effects": [{"value": 20}], "condition": {"kind": "element", "id": 1}},
    7104: {"family": "defense_power", "effects": [{"value": 15}]},
    7105: {"family": "range", "effects": [{"value": 1}]},
    7106: {"family": "permanent_revenge"},
}


def load_builder():
    path = Path("/Volumes/Data/Projects/D5/Subprojects/Engine-Extensions/integration/build_payload-158.py")
    spec = importlib.util.spec_from_file_location("build_payload_158", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(out_dir, config_name):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cfg = CONFIGS[config_name]
    overlord_compat.ACTIVE.update(cfg)
    builder = load_builder()
    # same call order as the project script, with the six-family evility section
    from d5lib import evility
    original = builder.evility.build_patch

    def build_patch(exe, rows, *a, **kw):
        return original(exe, FX, *a, **kw)

    builder.evility.build_patch = build_patch
    sys.argv = ["build_payload_158", str(out / f"payload-{config_name}")]
    (out / f"payload-{config_name}").mkdir(parents=True, exist_ok=True)
    builder.main()

    payload = (out / f"payload-{config_name}" / "payload.exe").read_bytes()
    vanilla = builder.PINNED.read_bytes()
    exe_out = out / f"payload-{config_name}.exe"
    exe_out.write_bytes(payload)
    receipt = overlord_compat.yield_receipt(payload, vanilla, cfg)
    receipt["configuration_name"] = config_name
    receipt["evility_families_built"] = sorted(FX[i]["family"] for i in FX)
    (out / f"yield-{config_name}.json").write_text(json.dumps(receipt, indent=1) + "\n")
    print(json.dumps(dict(config=config_name, verdict=receipt["verdict"],
                          findings=len(receipt["findings"]),
                          sites=[(r["site"], r["owner"]) for r in receipt["sites"]]), indent=1))
    return 0 if receipt["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
