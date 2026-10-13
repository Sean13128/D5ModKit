"""Unified access to every file inside the game's archives.

Virtual paths use '/' and start at the Data directory:
    Database/Database_0.dat/char.dat                 member of a NISPACK
    Anime/ANM_HI_JP.dat/anm00620.lzs                 LZS member (logical = decompressed)
    Map/Map_JP.dat/map30001.lzs/map30001.chr         member of the 'pac' inside an LZS
    Start/Start_JP.dat/Texture.dat/button.txf        member of a nested (plain) NISPACK
    Script/talk.dat                                  flat obfuscated file
    Sound_Voice/Sound_Voice_0.dat/voice_en/000100.dat/000100001.vag   a voice line (d5lib.fafs, d5lib.voices)

"Raw" bytes are exactly what is stored in the archive; "logical" bytes are what editors
work with (LZS / YKCMP decompressed).  `encode_like()` converts logical bytes back into
the stored representation of the original member.
"""
import os
import struct
import threading

from . import crypt, lzs, ykcmp, pac, nested
from .nispack import NisPack
from . import sound
from . import fafs

FLAT_FILES = ["Script/script.dat", "Script/talk.dat"]
EXE_FILE = "EXE/disgaea5.exe"   # virtual path of the game executable (raw, not obfuscated)
SOUND_FILES = ["Sound_Voice/Sound_Voice_0.dat", "Sound_Msg/Sound_Msg_0.dat"]
LANG_ARCHIVES = {  # kind -> archive template
    "anime": "Anime/ANM_HI_{}.dat",
    "map": "Map/Map_{}.dat",
    "object": "Object/Object_{}.dat",
    "start": "Start/Start_{}.dat",
}


def split_path(vpath: str):
    parts = [p for p in vpath.replace("\\", "/").split("/") if p]
    return "/".join(parts[:2]), parts[2:]


def is_lzs(raw: bytes) -> bool:
    if len(raw) < 16 or raw[3] != 0 or raw[:3] not in (b"dat", b"pac"):
        return False
    usize, csize = struct.unpack_from("<II", raw, 4)
    return csize + 4 == len(raw) or csize == len(raw)


def decode_member(raw: bytes) -> bytes:
    if is_lzs(raw):
        return lzs.decompress(raw)
    if ykcmp.is_ykcmp(raw):
        return ykcmp.decompress(raw)
    return raw


def lzs_compress(data: bytes, tag: bytes) -> bytes:
    try:
        from .lzs_compress import compress  # fast matcher (optional module)
        return compress(data, tag)
    except ImportError:
        return lzs_store(data, tag)


def lzs_store(data: bytes, tag: bytes) -> bytes:
    """Valid, uncompressed LZS stream (literals only, marker escaped)."""
    counts = [0] * 256
    for b in data[:1 << 20]:
        counts[b] += 1
    marker = min(range(256), key=counts.__getitem__)
    body = data.replace(bytes([marker]), bytes([marker, marker]))
    head = tag[:3].ljust(4, b"\0") + struct.pack("<III", len(data), len(body) + 12, marker)
    return head + body


def encode_like(logical: bytes, original_raw: bytes, name: str = None) -> bytes:
    """Re-encode edited logical content the same way the original member was stored.
    For brand-new members (original_raw None) the encoding is chosen from the file name."""
    if original_raw is None and name and name.lower().endswith(".lzs") and not is_lzs(logical):
        return lzs_compress(logical, b"pac\0" if name.lower().startswith("map") else b"dat\0")
    if original_raw is not None and is_lzs(original_raw):
        if is_lzs(logical):
            return logical
        return lzs_compress(logical, original_raw[:4])
    if original_raw is not None and ykcmp.is_ykcmp(original_raw):
        if ykcmp.is_ykcmp(logical):
            return logical
        return ykcmp.compress(logical)
    return logical


class GameFS:
    """Read-only view of the *vanilla* game data (uses install backups when mods are installed)."""

    def __init__(self, game_dir, backup_resolver=None):
        self.game_dir = os.path.abspath(game_dir)
        self.data_dir = os.path.join(self.game_dir, "Data")
        self._packs = {}
        self._lock = threading.RLock()
        self._backup_resolver = backup_resolver  # callable(archive) -> (header_bytes|None, full_copy_path|None)
        self._cache = {}
        self._kids = {}          # (archive, member) -> {child name: bytes} of the last containers read (_KIDS_BYTES)

    # ---------------------------------------------------------------- archives
    def archive_path(self, archive):
        if archive == EXE_FILE:
            return os.path.join(self.game_dir, "disgaea5.exe")
        return os.path.join(self.data_dir, archive.replace("/", os.sep))

    def archives(self):
        out = []
        for root, _, files in os.walk(self.data_dir):
            for fn in files:
                rel = os.path.relpath(os.path.join(root, fn), self.data_dir).replace(os.sep, "/")
                if rel.endswith(".dat"):
                    out.append(rel)
        return sorted(out)

    def archive_kind(self, archive):
        if archive in FLAT_FILES:
            return "flat"
        with open(self.archive_path(archive), "rb") as f:
            head = f.read(8)
        if fafs.is_fafs(head):
            return "fafs"
        if archive in SOUND_FILES:
            return "sound"
        if crypt.is_obfuscated_nispack(head):
            return "nispack"
        if sound.is_psfs(head):
            return "psfs"
        return "unknown"

    def pack(self, archive) -> NisPack:
        with self._lock:
            p = self._packs.get(archive)
            if p is None:
                path = self.archive_path(archive)
                header = self._backup_resolver(archive)[0] if self._backup_resolver else None
                with open(path, "rb") as f:
                    head = f.read(8)
                if sound.is_psfs(head):
                    p = sound.PsfsPack(path, header)
                elif fafs.is_fafs(head):
                    p = fafs.FafsPack(path, header)
                elif header is not None:
                    p = _pack_from_header(path, header)
                else:
                    p = NisPack(path)
                self._packs[archive] = p
            return p

    def reset(self):
        with self._lock:
            for p in self._packs.values():
                p.close()
            self._packs.clear()
            self._cache.clear()
            self._kids.clear()

    def list_members(self, archive):
        return self.pack(archive).names()

    def has_member(self, archive, name):
        return name.lower() in self.pack(archive).by_name

    # ---------------------------------------------------------------- reading
    def read_flat(self, archive) -> bytes:
        path = self.archive_path(archive)
        if self._backup_resolver:
            _, full = self._backup_resolver(archive)
            if full:
                path = full
        with open(path, "rb") as f:
            data = f.read()
        return data if archive == EXE_FILE else crypt.decode(data)

    def read_raw(self, vpath) -> bytes:
        archive, parts = split_path(vpath)
        if not parts:
            if archive in FLAT_FILES or archive == EXE_FILE:
                return self.read_flat(archive)
            raise ValueError("path must name a member: " + vpath)
        with self._lock:
            pk = self.pack(archive)
            if isinstance(pk, fafs.FafsPack):          # members are 'voice_en/000100.dat' (DSARC packs of lines)
                data = pk.read("/".join(parts[:2]))
                for seg in parts[2:]:
                    files = {k.lower(): v for k, v in fafs.pack_members(data).items()}
                    if seg.lower() not in files:
                        raise KeyError(f"{seg} not found in {vpath}")
                    data = files[seg.lower()]
                return data
            if len(parts) == 1:
                return pk.read(parts[0])
            # a file inside a container member: the container's files are kept (reading a texture list read and
            # decrypted its whole 40 MB pack for every picture, ~0.12 s each)
            ck = (archive.lower(), parts[0].lower())
            kids = self._kids.pop(ck, None)
            if kids is None:
                kids = _children(decode_member(pk.read(parts[0])))
            self._kids[ck] = kids                    # most recently used last
            while len(self._kids) > 1 and sum(_kids_size(k) for k in self._kids.values()) > _KIDS_BYTES:
                self._kids.pop(next(iter(self._kids)))
        if kids is None or parts[1].lower() not in kids:
            raise KeyError(f"{parts[1]} not found in {vpath}")
        data = kids[parts[1].lower()]
        for seg in parts[2:]:
            data = _child(decode_member(data), seg, vpath)
        return data

    def read(self, vpath) -> bytes:
        """Logical (decompressed) content."""
        key = vpath.lower()
        c = self._cache.get(key)
        if c is not None:
            return c
        archive, parts = split_path(vpath)
        if (archive in FLAT_FILES or archive == EXE_FILE) and not parts:
            return self.read_flat(archive)
        data = decode_member(self.read_raw(vpath))
        if len(data) < 4 << 20:
            self._cache[key] = data
        return data

    def children(self, vpath):
        """List members of a container member (pac or nested NISPACK); [] if not a container."""
        data = self.read(vpath)
        if nested.is_plain_nispack(data):
            return [n for n, _, _ in nested.read_plain(data)]
        if vpath.lower().endswith(".lzs"):
            raw = self.read_raw(vpath)
            if raw[:3] == b"pac":
                return [n for n, _ in pac.read_pac(data)]
        return []

    # ---------------------------------------------------------------- language layering
    def resolve(self, kind, name, lang="EN"):
        """Archive that the game would use for `name` in language `lang` (localized first, JP fallback)."""
        tmpl = LANG_ARCHIVES[kind]
        if lang != "JP":
            loc = tmpl.format(lang)
            if os.path.exists(self.archive_path(loc)) and self.has_member(loc, name):
                return loc
        return tmpl.format("JP")


_KIDS_BYTES = 256 << 20


def _children(container: bytes):
    """{child name (lower case): bytes} of a container (nested NISPACK or pac); {} for anything else"""
    if nested.is_plain_nispack(container):
        out = {}
        for n, d, _ in nested.read_plain(container):
            out.setdefault(n.lower(), d)
        return out
    try:
        out = {}
        for n, d in pac.read_pac(container):
            out.setdefault(n.lower(), d)
        return out
    except Exception:
        return {}


def _kids_size(kids):
    return sum(len(v) for v in kids.values())


def _child(container: bytes, name: str, vpath: str) -> bytes:
    if nested.is_plain_nispack(container):
        for n, d, _ in nested.read_plain(container):
            if n.lower() == name.lower():
                return d
    else:
        try:
            for n, d in pac.read_pac(container):
                if n.lower() == name.lower():
                    return d
        except Exception:
            pass
    raise KeyError(f"{name} not found in {vpath}")


def _pack_from_header(path, header: bytes) -> NisPack:
    """NisPack whose directory comes from a saved (obfuscated) header backup."""
    import io
    p = NisPack.__new__(NisPack)
    p.path = path
    p.fh = open(path, "rb")
    head = crypt.decode(header[:16])
    p.unk, count = struct.unpack_from("<II", head, 8)
    table = crypt.decode(header[16:16 + count * 44])
    from .nispack import Entry
    p.entries = []
    for i in range(count):
        name, off, size, stamp = struct.unpack_from("<32sIII", table, i * 44)
        p.entries.append(Entry(name.split(b"\0")[0].decode("ascii", "replace"), off, size, stamp))
    p.by_name = {e.name.lower(): e for e in p.entries}
    return p
