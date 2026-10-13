"""Disgaea 5 Complete (PC) -- Script/talk.dat : dialogue / event-trigger bytecode.

Layout (little endian, after de-obfuscation with d5lib.crypt):

    u32 count_a                (== count, both read by talkmanager)
    u32 count
    Record[count]              56 bytes each
    u8  code[]                 bytecode, starts right after the record table

    Record (0x38 bytes)
      +0x00 u32 offset         into code[]  (records are stored in code order, offsets strictly increasing)
      +0x04 u32 talk_id        key1: scene / talk number (0 = "stage trigger" records)
      +0x08 u16 key2           stage id (dungeon.dat) for stage triggers, 0 otherwise
      +0x0a u16 key3           trigger phase for stage triggers (1..4), 0 otherwise
      +0x0c u16 n_on           number of used entries in flags_on
      +0x0e u16 n_off          number of used entries in flags_off
      +0x10 u16 flags_on[10]   game flags that must be SET
      +0x24 u16 flags_off[10]  game flags that must be CLEAR

    The game picks the FIRST record whose keys match (0 in the query = wildcard) and whose
    flag conditions hold, then executes code from its offset until opcode 0xFF.

Bytecode: one opcode byte followed by fixed-size little endian operands (see OPS), except
  0x78..0x7C  text for language jp/en/fr/zh/ko : <op><utf-8 text>\\0\\0
  0x14 n      choice menu with n options; each option is "0x14" (only from the 2nd option on)
              followed by the option label strings and the code executed when it is picked
              (normally ending in 0xFF); the whole menu is closed by 0xFD.

Every record owns the bytes from its offset up to the next record's offset, so records can be
edited / grown / added / removed independently; offsets are recomputed on save.
"""
from __future__ import annotations

import json
import re
import struct
from typing import Dict, Iterable, List, Optional, Union

from . import crypt

LANG_BYTES = {0x78: "jp", 0x79: "en", 0x7A: "fr", 0x7B: "zh", 0x7C: "ko"}
LANG_OPS = {v: k for k, v in LANG_BYTES.items()}
LANGS = ["jp", "en", "fr", "zh", "ko"]

# opcode -> (mnemonic, operand byte sizes, description)
OPS: Dict[int, tuple] = {
    0x00: ("yield", [], "stop interpreting for this frame (rare)"),
    0x01: ("yield1", [], "same as 0x00 (unused)"),
    0x02: ("page", [], "wait for button, keep window (new page of the same message)"),
    0x03: ("msg_end", [], "wait for button, end of message box"),
    0x04: ("portrait0", [2, 2, 1], "bust slot 0: bust ref (1..24 = slot loaded by bust_load, 0xFFFF = hide), motion/expression, flip"),
    0x22: ("portrait1", [2, 2, 1], "bust slot 1"),
    0x0E: ("portrait2", [2, 2, 1], "bust slot 2"),
    0x2C: ("portrait3", [2, 2, 1], "bust slot 3"),
    0x18: ("portrait4", [2, 2, 1], "bust slot 4"),
    0x05: ("speaker", [2], "speaker: char.dat id (1..9 = party member n), 0xFFFF = none; name comes from char.dat"),
    0x06: ("voice", [4], "play voice clip id (Sound_Voice)"),
    0x07: ("window", [1, 1], "message window style, position"),
    0x08: ("nameplate", [2, 1], "name plate / face icon id (0xFFFF = none), flag"),
    0x09: ("flag_on", [2], "set game flag"),
    0x0A: ("flag_off", [2], "clear game flag"),
    0x0B: ("script", [3], "run script.dat event <id> and wait for it"),
    0x0C: ("goto_talk", [3], "jump to talk record with talk_id=<id> (conditions re-evaluated)"),
    0x0D: ("voice_next", [4], "preload next voice clip"),
    0x14: ("choice", [1], "choice menu with n options"),
    0x1E: ("op_1e", [3], "unknown (unused), UI effect"),
    0x28: ("portrait_fx", [1], "bitmask of bust slots to animate/highlight"),
    0x32: ("op_32", [1], "unknown, no effect in handler"),
    0x64: ("bust_load", [3], "load bup%05d.txf: value = slot*100000 + bust number (slot 1..24)"),
    0x65: ("wait_mode", [2, 1], "wait <frames> (0 -> 999), flag"),
    0x6E: ("bust_anim", [3], "slot*100000 + animation"),
    0x6F: ("bust_6f", [3], "slot*100000 + value (unused)"),
    0x70: ("bust_alpha", [3], "slot*100000 + value (unused)"),
    0x71: ("bust_move_r", [3], "slot*100000 + amount"),
    0x72: ("bust_move_l", [3], "slot*100000 + amount"),
    0x73: ("bust_73", [3], "slot*100000 + value (unused)"),
    0xC9: ("op_c9", [1], "window close style (unused)"),
    0xFA: ("text_speed", [1], "signed text speed (unused)"),
    0xFD: ("choice_end", [], "end of choice menu"),
    0xFE: ("wait_voice", [], "wait while voice plays"),
    0xFF: ("end", [], "end of talk"),
}
CHOICE_OPT = "option"          # pseudo mnemonic for the 0x14 separator before option 2..n
MNEM = {v[0]: k for k, v in OPS.items()}


class Ins:
    """One bytecode instruction. For text: op in 0x78..0x7C and .text holds the string."""
    __slots__ = ("op", "args", "text")

    def __init__(self, op: int, args: Optional[List[int]] = None, text: Optional[str] = None):
        self.op = op
        self.args = list(args or [])
        self.text = text

    # -- helpers
    @property
    def is_text(self) -> bool:
        return 0x78 <= self.op <= 0x7C and self.text is not None

    @property
    def is_option(self) -> bool:
        return self.op == 0x14 and self.text is None and self.args == []

    @property
    def lang(self) -> Optional[str]:
        return LANG_BYTES.get(self.op) if self.is_text else None

    @property
    def name(self) -> str:
        if self.is_text:
            return "text." + LANG_BYTES[self.op]
        if self.is_option:
            return CHOICE_OPT
        return OPS[self.op][0] if self.op in OPS else "op_%02x" % self.op

    def to_bytes(self) -> bytes:
        if self.is_text:
            return bytes([self.op]) + self.text.encode("utf-8", "surrogateescape") + b"\0\0"
        if self.is_option:
            return b"\x14"
        out = bytearray([self.op])
        for size, v in zip(OPS[self.op][1], self.args):
            out += int(v).to_bytes(size, "little", signed=False)
        return bytes(out)

    def __len__(self):
        return len(self.to_bytes())

    def __repr__(self):
        if self.is_text:
            return "Ins(%s %r)" % (self.name, self.text)
        return "Ins(%s %s)" % (self.name, self.args)

    @staticmethod
    def text_line(lang: str, text: str) -> "Ins":
        return Ins(LANG_OPS[lang], text=text)

    @staticmethod
    def make(name: str, *args: int) -> "Ins":
        if name == CHOICE_OPT:
            return Ins(0x14)
        if name.startswith("text."):
            return Ins.text_line(name[5:], args[0])
        op = MNEM[name] if name in MNEM else int(name[3:], 16)
        return Ins(op, list(args))


def parse_code(data: bytes, pos: int = 0, end: Optional[int] = None) -> List[Ins]:
    """Linear disassembly of talk bytecode."""
    end = len(data) if end is None else end
    out: List[Ins] = []
    p = pos
    while p < end:
        op = data[p]
        if 0x78 <= op <= 0x7C:
            e = data.index(b"\0", p + 1)
            if data[e + 1] != 0:
                raise ValueError("text at %#x not terminated by 00 00" % p)
            out.append(Ins(op, text=data[p + 1:e].decode("utf-8", "surrogateescape")))
            p = e + 2
            continue
        if op == 0x14 and p + 1 < end and data[p + 1] == 0x78:
            out.append(Ins(0x14))
            p += 1
            continue
        if op not in OPS:
            raise ValueError("unknown talk opcode %#04x at %#x" % (op, p))
        q = p + 1
        args = []
        for size in OPS[op][1]:
            args.append(int.from_bytes(data[q:q + size], "little"))
            q += size
        out.append(Ins(op, args))
        p = q
    return out


class TalkRecord:
    __slots__ = ("talk_id", "key2", "key3", "flags_on", "flags_off", "code")

    def __init__(self, talk_id=0, key2=0, key3=0, flags_on=(), flags_off=(), code=None):
        self.talk_id = talk_id
        self.key2 = key2
        self.key3 = key3
        self.flags_on = list(flags_on)
        self.flags_off = list(flags_off)
        self.code: List[Ins] = list(code or [])

    # aliases with the meaning they have for stage-trigger records (talk_id == 0)
    @property
    def stage(self):
        return self.key2

    @property
    def phase(self):
        return self.key3

    def header_bytes(self, offset: int) -> bytes:
        if len(self.flags_on) > 10 or len(self.flags_off) > 10:
            raise ValueError("max 10 flags per condition list")
        on = self.flags_on + [0] * (10 - len(self.flags_on))
        off = self.flags_off + [0] * (10 - len(self.flags_off))
        return struct.pack("<II4H10H10H", offset, self.talk_id, self.key2, self.key3,
                           len(self.flags_on), len(self.flags_off), *on, *off)

    def code_bytes(self) -> bytes:
        return b"".join(i.to_bytes() for i in self.code)

    def texts(self, lang: str = "en") -> List[str]:
        return [i.text for i in self.code if i.lang == lang]

    def __repr__(self):
        return "TalkRecord(talk_id=%d key2=%d key3=%d on=%s off=%s, %d ins)" % (
            self.talk_id, self.key2, self.key3, self.flags_on, self.flags_off, len(self.code))


class Message:
    """A message box reconstructed from the bytecode (for dumping / editing)."""

    def __init__(self):
        self.speaker = None      # char.dat id
        self.nameplate = None
        self.voice = None
        self.window = None
        self.portraits = {}      # slot -> (bust_ref, motion, flip)
        self.lines: List[Dict[str, Ins]] = []   # each line: lang -> Ins
        self.end_op = None       # 0x02 page / 0x03 msg_end

    def text(self, lang="en", sep="\n") -> str:
        return sep.join(l[lang].text for l in self.lines if lang in l)


class TalkFile:
    def __init__(self):
        self.count_a = 0
        self.records: List[TalkRecord] = []

    # ---------------------------------------------------------------- I/O
    @staticmethod
    def _looks_plain(b: bytes) -> bool:
        if len(b) < 8:
            return False
        a, n = struct.unpack_from("<II", b)
        return a == n and 8 + n * 56 <= len(b)

    @classmethod
    def from_bytes(cls, b: bytes) -> "TalkFile":
        if not cls._looks_plain(b):
            dec = crypt.decode(b)
            if not cls._looks_plain(dec):
                raise ValueError("not a talk.dat")
            b = dec
        self = cls()
        self.count_a, n = struct.unpack_from("<II", b)
        base = 8 + n * 56
        data = b[base:]
        hdr = [struct.unpack_from("<II4H10H10H", b, 8 + 56 * k) for k in range(n)]
        offs = [h[0] for h in hdr]
        if offs != sorted(offs):
            raise ValueError("record offsets not ascending - unsupported layout")
        bounds = offs[1:] + [len(data)]
        for h, end in zip(hdr, bounds):
            off, tid, k2, k3, non, noff = h[:6]
            rec = TalkRecord(tid, k2, k3, h[6:6 + non], h[16:16 + noff])
            rec.code = parse_code(data, off, end)
            self.records.append(rec)
        return self

    @classmethod
    def load(cls, path: str) -> "TalkFile":
        with open(path, "rb") as f:
            return cls.from_bytes(f.read())

    def to_bytes(self) -> bytes:
        n = len(self.records)
        heads, blobs, off = [], [], 0
        for r in self.records:
            c = r.code_bytes()
            heads.append(r.header_bytes(off))
            blobs.append(c)
            off += len(c)
        # both header words hold the record count (the game reads both)
        return struct.pack("<II", n, n) + b"".join(heads) + b"".join(blobs)

    def save(self, path: str, obfuscate: bool = True):
        b = self.to_bytes()
        with open(path, "wb") as f:
            f.write(crypt.encode(b) if obfuscate else b)

    # ---------------------------------------------------------------- queries
    def find(self, talk_id=None, key2=None, key3=None) -> List[TalkRecord]:
        return [r for r in self.records
                if (talk_id is None or r.talk_id == talk_id)
                and (key2 is None or r.key2 == key2)
                and (key3 is None or r.key3 == key3)]

    def lookup(self, talk_id=0, key2=0, key3=0, flags: Iterable[int] = ()) -> Optional[TalkRecord]:
        """Emulates the game's selection (talkmanager 0x14019b3f0): first record whose keys match
        (a 0 in the query matches anything) and whose flag conditions hold for the flag set."""
        fs = set(flags)
        for r in self.records:
            if talk_id and r.talk_id != talk_id:
                continue
            if key2 and r.key2 != key2:
                continue
            if key3 and r.key3 != key3:
                continue
            if all(f in fs for f in r.flags_on) and not any(f in fs for f in r.flags_off):
                return r
        return None

    # ---------------------------------------------------------------- editing
    def add_record(self, rec: TalkRecord, index: Optional[int] = None) -> TalkRecord:
        """Insert a record (default: at the end). Note the game takes the FIRST matching record,
        so a new variant of an existing talk_id must be inserted BEFORE the old ones."""
        if index is None:
            self.records.append(rec)
        else:
            self.records.insert(index, rec)
        return rec

    def remove_record(self, rec: TalkRecord):
        self.records.remove(rec)

    @staticmethod
    def build_message(texts: Union[Dict[str, str], List[Dict[str, str]]], speaker: Optional[int] = None,
                      voice: Optional[int] = None, window=(2, 0), end_op=0x03,
                      nameplate: Optional[int] = None) -> List[Ins]:
        """Instructions for one message box. `texts` = {lang: text} or a list of those (one per line,
        max 3 lines fit). Missing languages fall back to 'en' (or first given)."""
        if isinstance(texts, dict):
            texts = [texts]
        out = []
        if window is not None:
            out.append(Ins(0x07, list(window)))
        if speaker is not None:
            out.append(Ins(0x05, [speaker]))
        if voice is not None:
            out.append(Ins(0x06, [voice]))
        if nameplate is not None:
            out.append(Ins(0x08, [nameplate, 0]))
        for line in texts:
            fallback = line.get("en", next(iter(line.values())))
            for lang in LANGS:
                out.append(Ins.text_line(lang, line.get(lang, fallback)))
        out.append(Ins(end_op))
        return out

    # ---------------------------------------------------------------- views
    @staticmethod
    def messages(rec: TalkRecord) -> List[Message]:
        """Group a record's code into message boxes (speaker/voice/portrait state carried along)."""
        msgs, cur = [], Message()
        state = {"speaker": None, "voice": None, "window": None, "nameplate": None, "portraits": {}}
        line: Dict[str, Ins] = {}
        slot_of = {0x04: 0, 0x22: 1, 0x0E: 2, 0x2C: 3, 0x18: 4}
        for ins in rec.code:
            if ins.is_text:
                if ins.lang in line:
                    cur.lines.append(line)
                    line = {}
                line[ins.lang] = ins
                continue
            if line:
                cur.lines.append(line)
                line = {}
            op = ins.op
            if op == 0x05:
                state["speaker"] = ins.args[0]
            elif op == 0x06:
                state["voice"] = ins.args[0]
            elif op == 0x07:
                state["window"] = tuple(ins.args)
            elif op == 0x08:
                state["nameplate"] = ins.args[0]
            elif op in slot_of:
                state["portraits"][slot_of[op]] = tuple(ins.args)
            elif op in (0x02, 0x03, 0x14) or ins.is_option:
                if cur.lines:
                    cur.speaker, cur.voice = state["speaker"], state["voice"]
                    cur.window, cur.nameplate = state["window"], state["nameplate"]
                    cur.portraits = dict(state["portraits"])
                    cur.end_op = op
                    msgs.append(cur)
                    cur = Message()
                if op == 0x03:
                    state["voice"] = None
        if line:
            cur.lines.append(line)
        if cur.lines:
            cur.speaker, cur.voice = state["speaker"], state["voice"]
            msgs.append(cur)
        return msgs

    # ---------------------------------------------------------------- text format
    def disassemble(self, records: Optional[Iterable[TalkRecord]] = None) -> str:
        """Human readable / re-assemblable text. Text strings are JSON-quoted."""
        out = ["; talk.dat disassembly (d5lib.talk). count_a=%d" % self.count_a]
        recs = self.records if records is None else records
        for r in recs:
            out.append("")
            out.append("record talk=%d key2=%d key3=%d on=%s off=%s" % (
                r.talk_id, r.key2, r.key3, ",".join(map(str, r.flags_on)) or "-",
                ",".join(map(str, r.flags_off)) or "-"))
            for ins in r.code:
                if ins.is_text:
                    out.append("  %s %s" % (ins.name, json.dumps(ins.text, ensure_ascii=False)))
                else:
                    out.append("  " + " ".join([ins.name] + [str(a) for a in ins.args]))
        return "\n".join(out) + "\n"

    @classmethod
    def assemble(cls, text: str) -> "TalkFile":
        self = cls()
        rec = None
        for ln in text.splitlines():
            s = ln.strip()
            if not s or s.startswith(";"):
                m = re.match(r";.*count_a=(\d+)", s)
                if m:
                    self.count_a = int(m.group(1))
                continue
            if s.startswith("record "):
                kv = dict(x.split("=", 1) for x in s[7:].split())
                lst = lambda v: [] if v == "-" else [int(x) for x in v.split(",")]
                rec = TalkRecord(int(kv["talk"]), int(kv["key2"]), int(kv["key3"]), lst(kv["on"]), lst(kv["off"]))
                self.records.append(rec)
                continue
            if rec is None:
                raise ValueError("instruction outside record: %r" % ln)
            name, _, rest = s.partition(" ")
            if name.startswith("text."):
                rec.code.append(Ins.text_line(name[5:], json.loads(rest)))
            else:
                rec.code.append(Ins.make(name, *[int(x, 0) for x in rest.split()]))
        if not self.count_a:
            self.count_a = len(self.records)
        return self


def char_names(char_dat: bytes, lang: str = "en") -> Dict[int, str]:
    """id -> name from Database/char.dat (record 908 bytes, id u16 @0xDE, names 52-byte slots @0xF8)."""
    n = struct.unpack_from("<I", char_dat)[0]
    slot = LANGS.index(lang)
    out = {}
    for k in range(n):
        r = char_dat[4 + k * 908:4 + (k + 1) * 908]
        cid = struct.unpack_from("<H", r, 0xDE)[0]
        name = r[0xF8 + slot * 0x34:0xF8 + (slot + 1) * 0x34].split(b"\0")[0].decode("utf-8", "replace")
        out.setdefault(cid, name)
    return out
