"""Music archive (Sound_BGM_*.dat, magic 'PS_FS_V1').

Header: 'PS_FS_V1', u64 count, then count x {char name[48], u64 length, u64 offset}; data 512-aligned.
Each member ('NNN.ogg') = 7 x u32 metadata + concatenated Ogg Vorbis streams:
    [7, ogg_total_bytes, 113536, total_samples, intro_bytes, loop_bytes, outro_bytes]
Playback: intro once, then loop forever (outro is never played).  The number NNN is referenced
by `music.dat` (field `file`).

Sound effects (Sound_SE_0.dat, magic 'DSARC FL'):
Header: 'DSARC FL', u64 count, then count x {char name[116], u32 length, u32 offset, u32 0}; 512-aligned.
Each member ('NNNN.vag') = 7 x u32 [5, wav_bytes, sample_rate, samples, 0, wav_bytes, 0] + RIFF WAV (MS-ADPCM).
"""
import struct
from dataclasses import dataclass

MAGIC = b"PS_FS_V1"
DSARC_MAGIC = b"DSARC FL"
ALIGN = 0x200
TOC_ENTRY = 64
DSARC_ENTRY = 128


@dataclass
class Entry:
    name: str
    offset: int
    size: int
    stamp: int = 0


def parse_toc(header: bytes):
    count = struct.unpack_from("<Q", header, 8)[0]
    out = []
    if header[:8] == MAGIC:
        for i in range(count):
            name, ln, off = struct.unpack_from("<48sQQ", header, 16 + i * TOC_ENTRY)
            out.append(Entry(name.split(b"\0")[0].decode("ascii", "replace"), off, ln))
    elif header[:8] == DSARC_MAGIC:
        for i in range(count):
            name, ln, off, _ = struct.unpack_from("<116sIII", header, 16 + i * DSARC_ENTRY)
            out.append(Entry(name.split(b"\0")[0].decode("ascii", "replace"), off, ln))
    else:
        raise ValueError("not a sound archive")
    return out


def entry_size(magic: bytes) -> int:
    return TOC_ENTRY if magic[:8] == MAGIC else DSARC_ENTRY


class PsfsPack:
    """Reader for PS_FS_V1 (music) and DSARC FL (sound effects) archives."""

    def __init__(self, path, header: bytes = None):
        self.path = path
        self.fh = open(path, "rb")
        if header is None:
            head = self.fh.read(16)
            count = struct.unpack_from("<Q", head, 8)[0]
            header = head + self.fh.read(count * entry_size(head))
        self.magic = header[:8]
        self.entries = parse_toc(header)
        self.by_name = {e.name.lower(): e for e in self.entries}

    def names(self):
        return [e.name for e in self.entries]

    def read(self, entry):
        if isinstance(entry, str):
            entry = self.by_name[entry.lower()]
        self.fh.seek(entry.offset)
        return self.fh.read(entry.size)

    def close(self):
        self.fh.close()


def is_psfs(head: bytes) -> bool:
    return head[:8] in (MAGIC, DSARC_MAGIC)


def header_length(path) -> int:
    """Bytes before the first member (the region the installer backs up)."""
    with open(path, "rb") as f:
        head = f.read(16)
        count = struct.unpack_from("<Q", head, 8)[0]
        toc = head + f.read(count * entry_size(head))
    offs = [e.offset for e in parse_toc(toc)]
    return min(offs) if offs else 16


def write_toc(entries, magic=MAGIC) -> bytes:
    out = bytearray(magic + struct.pack("<Q", len(entries)))
    for e in entries:
        if magic == MAGIC:
            out += struct.pack("<48sQQ", e.name.encode("ascii")[:48], e.size, e.offset)
        else:
            out += struct.pack("<116sIII", e.name.encode("ascii")[:116], e.size, e.offset, 0)
    return bytes(out)


# ------------------------------------------------------------------------------ track helpers
def parse_track(data: bytes) -> dict:
    m = struct.unpack_from("<7I", data, 0)
    ogg = data[28:]
    a, b, c = m[4], m[5], m[6]
    return {"meta": m, "samples": m[3], "intro": ogg[:a], "loop": ogg[a:a + b], "outro": ogg[a + b:a + b + c]}


def ogg_samples(ogg: bytes) -> int:
    """Last granule position of an Ogg stream (= number of PCM samples)."""
    i = ogg.rfind(b"OggS")
    while i >= 0:
        if i + 14 <= len(ogg):
            g = struct.unpack_from("<q", ogg, i + 6)[0]
            if g >= 0:
                return g
        i = ogg.rfind(b"OggS", 0, i)
    return 0


def ogg_info(ogg: bytes) -> dict:
    """Channels / sample rate from the Vorbis identification header."""
    i = ogg.find(b"\x01vorbis")
    if i < 0:
        return {}
    ch = ogg[i + 11]
    rate = struct.unpack_from("<I", ogg, i + 12)[0]
    return {"channels": ch, "rate": rate, "samples": ogg_samples(ogg)}


def build_track(loop: bytes, intro: bytes = b"", outro: bytes = b"") -> bytes:
    for part in (intro, loop, outro):
        if part and part[:4] != b"OggS":
            raise ValueError("music parts must be Ogg Vorbis files")
    samples = sum(ogg_samples(p) for p in (intro, loop, outro) if p)
    total = len(intro) + len(loop) + len(outro)
    meta = struct.pack("<7I", 7, total, 113536, samples, len(intro), len(loop), len(outro))
    return meta + intro + loop + outro


def track_to_ogg(data: bytes) -> bytes:
    """Playable single Ogg of intro+loop (chained Ogg streams are valid Ogg)."""
    t = parse_track(data)
    return t["intro"] + t["loop"]


# ------------------------------------------------------------------------------ sound effects
def parse_se(data: bytes) -> dict:
    m = struct.unpack_from("<7I", data, 0)
    return {"meta": m, "rate": m[2], "samples": m[3], "wav": data[28:28 + m[1]]}


def wav_info(wav: bytes) -> dict:
    """Parse the RIFF fmt chunk and data length."""
    info = {}
    i = 12
    while i + 8 <= len(wav):
        cid, ln = wav[i:i + 4], struct.unpack_from("<I", wav, i + 4)[0]
        if cid == b"fmt ":
            fmt, ch, rate, bps, align, bits = struct.unpack_from("<HHIIHH", wav, i + 8)
            info.update(format=fmt, channels=ch, rate=rate, block_align=align, bits=bits)
            if fmt == 2 and ln >= 20:
                info["samples_per_block"] = struct.unpack_from("<H", wav, i + 26)[0]
        elif cid == b"fact":
            info["fact_samples"] = struct.unpack_from("<I", wav, i + 8)[0]
        elif cid == b"data":
            info["data_len"] = ln
        i += 8 + ln + (ln & 1)
    return info


def wav_samples(wav: bytes) -> int:
    i = wav_info(wav)
    if "fact_samples" in i:
        return i["fact_samples"]
    if i.get("format") == 1 and i.get("block_align"):
        return i.get("data_len", 0) // i["block_align"]
    if i.get("format") == 2 and i.get("block_align"):
        return int(i.get("data_len", 0) / i["block_align"] * i.get("samples_per_block", 0))
    return 0


def build_se(wav: bytes, rate: int = None) -> bytes:
    if wav[:4] != b"RIFF":
        raise ValueError("sound effects must be WAV files")
    i = wav_info(wav)
    meta = struct.pack("<7I", 5, len(wav), rate or i.get("rate", 48000), wav_samples(wav), 0, len(wav), 0)
    return meta + wav
