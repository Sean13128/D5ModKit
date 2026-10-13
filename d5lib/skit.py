"""Disgaea 5 Complete (PC) -- Skit/Skit_0.dat members skitNNNN.dat (2D "skit" conversations, skit.cpp).

Skit_0.dat is an obfuscated NISPACK (d5lib.nispack.NisPack.read returns plain members):

    u32  count
    char name[86]           e.g. "101" (the skit number), zero padded
    Cmd  cmds[count]        0xB60 (2912) bytes each

    Cmd
      +0x000 u32   type     command type 0..19 (switch in 0x1402c7370)
      +0x004 s32   p[367]   parameters (only a few are used per type, see TYPES)
      +0x5C0 char  text[3][5][96]   3 lines x (jp,en,fr,zh,ko), UTF-8, NUL padded

The executor runs one command per step: index into the table with `cmd * 0xB60`.
"""
from __future__ import annotations

import json
import struct
from typing import Dict, List, Optional

LANGS = ["jp", "en", "fr", "zh", "ko"]
REC_SIZE = 0xB60
HDR_SIZE = 0x5A
TEXT_OFF = 0x5C0
SLOT = 0x60
N_LINES = 3

# type -> (name, confidence, {param offset: field name})   (observed usage over all 109 skits)
TYPES: Dict[int, tuple] = {
    0: ("char_show", "M", {0x04: "char", 0x08: "x"}),          # place/show a skit character at x
    1: ("text", "H", {}),                                        # one text line (texts in text[0])
    3: ("sound", "L", {0x04: "id"}),
    4: ("shake", "L", {0x04: "mode", 0x08: "power", 0x0C: "count"}),
    5: ("char_move", "L", {0x04: "slot", 0x08: "x", 0x0C: "frames"}),
    6: ("char_jump", "L", {0x04: "slot", 0x08: "height", 0x0C: "frames"}),
    7: ("char_fx", "L", {0x04: "slot", 0x08: "mode", 0x0C: "frames"}),
    8: ("char_face", "M", {0x04: "slot", 0x08: "expression"}),
    9: ("fade", "L", {0x04: "alpha", 0x08: "frames_in", 0x0C: "frames_out"}),
    10: ("speaker_off", "L", {0x1C: "char"}),
    11: ("speaker", "M", {0x1C: "char"}),                        # -1 = nobody
    12: ("text_speed", "L", {0x18: "value"}),
    13: ("wait", "M", {0x04: "frames"}),
    14: ("wait_key", "M", {}),                                  # end of message box
    15: ("type15", "L", {}),
    16: ("char_hide", "L", {0x04: "char"}),
    18: ("end", "M", {}),
}
BY_NAME = {v[0]: k for k, v in TYPES.items()}


class SkitCmd:
    __slots__ = ("type", "params", "text")

    def __init__(self, type_: int = 0, params: Optional[Dict[int, int]] = None,
                 text: Optional[List[Dict[str, str]]] = None):
        self.type = type_
        self.params: Dict[int, int] = dict(params or {})        # byte offset -> s32 (non-zero only)
        self.text: List[Dict[str, str]] = [dict(t) for t in (text or [{} for _ in range(N_LINES)])]
        while len(self.text) < N_LINES:
            self.text.append({})

    @property
    def name(self) -> str:
        return TYPES[self.type][0] if self.type in TYPES else "type%d" % self.type

    def field(self, name: str) -> int:
        for off, n in TYPES.get(self.type, ("", "", {}))[2].items():
            if n == name:
                return self.params.get(off, 0)
        raise KeyError(name)

    def set_field(self, name: str, value: int):
        for off, n in TYPES.get(self.type, ("", "", {}))[2].items():
            if n == name:
                if value:
                    self.params[off] = value
                else:
                    self.params.pop(off, None)
                return
        raise KeyError(name)

    def to_bytes(self) -> bytes:
        b = bytearray(REC_SIZE)
        struct.pack_into("<I", b, 0, self.type)
        for off, v in self.params.items():
            if not 4 <= off < TEXT_OFF or off % 4:
                raise ValueError("bad param offset %#x" % off)
            struct.pack_into("<i", b, off, v)
        for li, line in enumerate(self.text):
            for lang, s in line.items():
                raw = s.encode("utf-8")
                if len(raw) >= SLOT:
                    raise ValueError("skit text too long (%d bytes, max 95): %r" % (len(raw), s))
                o = TEXT_OFF + (li * 5 + LANGS.index(lang)) * SLOT
                b[o:o + len(raw)] = raw
        return bytes(b)

    @classmethod
    def from_bytes(cls, r: bytes) -> "SkitCmd":
        t = struct.unpack_from("<I", r, 0)[0]
        params = {}
        for off in range(4, TEXT_OFF, 4):
            v = struct.unpack_from("<i", r, off)[0]
            if v:
                params[off] = v
        text = []
        for li in range(N_LINES):
            line = {}
            for k, lang in enumerate(LANGS):
                o = TEXT_OFF + (li * 5 + k) * SLOT
                s = r[o:o + SLOT].split(b"\0")[0]
                if s:
                    line[lang] = s.decode("utf-8")
            text.append(line)
        return cls(t, params, text)

    def to_json(self) -> dict:
        d = {"cmd": self.name}
        names = TYPES.get(self.type, ("", "", {}))[2]
        extra = {}
        for off, v in sorted(self.params.items()):
            if off in names:
                d[names[off]] = v
            else:
                extra["%#x" % off] = v
        if extra:
            d["params"] = extra
        lines = [l for l in self.text]
        while lines and not lines[-1]:
            lines.pop()
        if lines:
            d["text"] = lines
        return d

    @classmethod
    def from_json(cls, d: dict) -> "SkitCmd":
        name = d["cmd"]
        t = BY_NAME[name] if name in BY_NAME else int(name[4:])
        c = cls(t)
        names = {v: k for k, v in TYPES.get(t, ("", "", {}))[2].items()}
        for k, v in d.items():
            if k in names and v:
                c.params[names[k]] = v
        for k, v in d.get("params", {}).items():
            c.params[int(k, 0)] = v
        for i, line in enumerate(d.get("text", [])):
            c.text[i] = dict(line)
        return c

    def __repr__(self):
        return "SkitCmd(%s %s)" % (self.name, {k: v for k, v in self.to_json().items() if k != "cmd"})


class SkitFile:
    def __init__(self, name: str = "", cmds: Optional[List[SkitCmd]] = None):
        self.name = name
        self.cmds: List[SkitCmd] = list(cmds or [])

    @classmethod
    def from_bytes(cls, b: bytes) -> "SkitFile":
        n = struct.unpack_from("<I", b)[0]
        if HDR_SIZE + n * REC_SIZE != len(b):
            raise ValueError("size mismatch: %d cmds, %d bytes" % (n, len(b)))
        hdr = b[4:HDR_SIZE]
        name = hdr.split(b"\0")[0].decode("ascii")
        if any(hdr[len(name):]):
            raise ValueError("unexpected data in skit header")
        self = cls(name)
        for k in range(n):
            self.cmds.append(SkitCmd.from_bytes(b[HDR_SIZE + k * REC_SIZE:HDR_SIZE + (k + 1) * REC_SIZE]))
        return self

    @classmethod
    def load(cls, path: str) -> "SkitFile":
        with open(path, "rb") as f:
            return cls.from_bytes(f.read())

    def to_bytes(self) -> bytes:
        nm = self.name.encode("ascii")
        if len(nm) >= HDR_SIZE - 4:
            raise ValueError("name too long")
        hdr = struct.pack("<I", len(self.cmds)) + nm + b"\0" * (HDR_SIZE - 4 - len(nm))
        return hdr + b"".join(c.to_bytes() for c in self.cmds)

    def save(self, path: str):
        with open(path, "wb") as f:
            f.write(self.to_bytes())

    # ---- text (JSON lines) ------------------------------------------------
    def to_text(self) -> str:
        out = ['# skit %s  (d5lib.skit, one JSON object per command)' % self.name]
        for c in self.cmds:
            out.append(json.dumps(c.to_json(), ensure_ascii=False))
        return "\n".join(out) + "\n"

    @classmethod
    def from_text(cls, text: str) -> "SkitFile":
        lines = text.splitlines()
        name = lines[0].split()[2] if lines and lines[0].startswith("# skit ") else ""
        self = cls(name)
        for ln in lines:
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                self.cmds.append(SkitCmd.from_json(json.loads(ln)))
        return self

    def dialogue(self, lang: str = "en"):
        """Yields (speaker char id or None, message text) for each message box."""
        speaker, buf = None, []
        for c in self.cmds:
            if c.type == 11:
                speaker = c.params.get(0x1C)
                speaker = None if speaker in (None, -1) else speaker
            elif c.type == 1:
                buf.extend(l[lang] for l in c.text if lang in l)
            elif c.type == 14 and buf:
                yield speaker, " ".join(buf)
                buf = []
        if buf:
            yield speaker, " ".join(buf)
