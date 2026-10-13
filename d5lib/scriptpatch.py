"""Event-script patches (script.dat), composable between mods.

Stored in a mod as patches/script/script.json:
{"events": {"<event id>": "<disassembly of that event>"}}
Existing ids replace the event (first match, as the game uses); unknown ids are appended.
"""
import csv
import os

from . import script
from .modsys import register_patch_handler

SCRIPT = "Script/script.dat"
GROUPS = {0x01: "flow", 0x0A: "variables", 0x14: "flags", 0x46: "sound", 0x50: "map", 0x64: "characters",
          0x65: "characters", 0x66: "characters", 0x6E: "talk/portraits", 0x72: "effects", 0x78: "items/state",
          0x7C: "items/state"}
_hints = None


def hints():
    """opcode -> short description (from the executable analysis)."""
    global _hints
    if _hints is None:
        _hints = {}
        p = os.path.join(os.path.dirname(__file__), "data", "script_opcodes.tsv")
        try:
            with open(p, encoding="utf-8") as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    h = (r.get("name_or_hint") or "").strip()
                    if h and h != "-":
                        _hints[int(r["opcode"], 16)] = h
        except OSError:
            pass
    return _hints


def event_text(ev, annotate=True) -> str:
    lines = script.disassemble_event(ev)
    lines = [l for l in lines if l.strip()]
    if not annotate:
        return "\n".join(lines) + "\n"
    h = hints()
    # annotate by walking instructions in order (labels are separate lines)
    res = [lines[0]]
    it = iter(ev.code)
    for ln in lines[1:]:
        s = ln.strip()
        if s.endswith(":") and " " not in s:
            res.append(ln)
            continue
        ins = next(it, None)
        note = ""
        if ins is not None and not s.startswith("set_string"):
            desc = h.get(ins.cid)
            grp = GROUPS.get(ins.cid >> 8)
            if desc or grp:
                note = "   ; " + (desc or grp)
        res.append(ln + note)
    return "\n".join(res) + "\n"


def parse_event_text(text: str):
    sf = script.ScriptFile.assemble(text)
    if len(sf.events) != 1:
        raise ValueError("the text must contain exactly one 'event <id>' block")
    return sf.events[0]


def diff(vanilla: script.ScriptFile, edited: script.ScriptFile) -> dict:
    van = {}
    for e in vanilla.events:
        van.setdefault(e.id, e)
    out = {}
    seen = set()
    for e in edited.events:
        if e.id in seen:
            continue
        seen.add(e.id)
        v = van.get(e.id)
        if v is None or (v is not e and v.encode() != e.encode()):        # same object: not edited
            out[str(e.id)] = event_text(e, annotate=False)
    return {"events": out} if out else {}


def apply(sf: script.ScriptFile, patch: dict):
    for eid, text in (patch.get("events") or {}).items():
        ev = parse_event_text(text)
        for i, e in enumerate(sf.events):
            if e.id == ev.id:
                sf.events[i] = ev
                break
        else:
            sf.events.append(ev)


def _handler(ctx, mod, patch_dir):
    for fname in mod.list_patches("script"):
        patch = mod.load_patch("script", fname)
        sf = ctx.parsed(SCRIPT, script.ScriptFile.from_bytes)
        apply(sf, patch)
        ctx.changed(SCRIPT, script.ScriptFile.to_bytes)
        ctx.log(f"  scripts: {len(patch.get('events', {}))} event(s) changed/added")


register_patch_handler("script", _handler, order=30)
