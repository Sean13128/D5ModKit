"""Dialogue patches (talk.dat), composable between mods.

Stored in a mod as patches/text/talk.json:
{
  "records": {"<record index>": "<disassembly of that one record>"},   # replaced records
  "added":   ["<disassembly of a new record>", ...]                   # appended records
}
The disassembly format is d5lib.talk.TalkFile.disassemble() (one 'record ...' header + instructions).
"""
from . import talk
from .modsys import register_patch_handler

TALK = "Script/talk.dat"


def record_text(tf: talk.TalkFile, rec) -> str:
    lines = tf.disassemble([rec]).splitlines()
    return "\n".join(l for l in lines if l and not l.startswith(";")) + "\n"


def parse_record(text: str):
    t = talk.TalkFile.assemble(text)
    if len(t.records) != 1:
        raise ValueError("a record patch must contain exactly one 'record' block")
    return t.records[0]


def diff(vanilla: talk.TalkFile, edited: talk.TalkFile) -> dict:
    out = {}
    recs = {}
    for i in range(min(len(vanilla.records), len(edited.records))):
        a, b = vanilla.records[i], edited.records[i]
        if a.code_bytes() != b.code_bytes() or a.header_bytes(0) != b.header_bytes(0):
            recs[str(i)] = record_text(edited, b)
    if recs:
        out["records"] = recs
    if len(edited.records) > len(vanilla.records):
        out["added"] = [record_text(edited, r) for r in edited.records[len(vanilla.records):]]
    return out


def apply(tf: talk.TalkFile, patch: dict):
    for idx, text in (patch.get("records") or {}).items():
        i = int(idx)
        if i < len(tf.records):
            tf.records[i] = parse_record(text)
    for text in patch.get("added") or []:
        tf.records.append(parse_record(text))


def _handler(ctx, mod, patch_dir):
    for fname in mod.list_patches("text"):
        if fname.lower() != "talk.json":
            continue
        patch = mod.load_patch("text", fname)
        tf = talk.TalkFile.from_bytes(ctx.get(TALK))
        apply(tf, patch)
        ctx.put(TALK, tf.to_bytes())
        ctx.log(f"  dialogue: {len(patch.get('records', {}))} edited, {len(patch.get('added', []))} added records")


register_patch_handler("text", _handler, order=20)
