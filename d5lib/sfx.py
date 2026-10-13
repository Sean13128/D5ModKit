"""Sound effects for the kit's skill preview: Data/Sound_SE/Sound_SE_0.dat (DSARC FL, d5lib/sound.py) members
NNNN.vag = 28-byte header + RIFF WAV in MS-ADPCM (mostly mono, ~48 kHz), decoded to float PCM here.

`se_play id, volume, speed` (cmd 0x4612, handler 0x14018b5c0): sound NNNN.vag = id, volume in percent (the game
divides by 100), speed / pitch where 1000 = normal (the game divides by 10 and by 100).
"""
import os
import struct

import numpy as np

from . import sound

ARCHIVE = os.path.join("Sound_SE", "Sound_SE_0.dat")
ADAPT = [230, 230, 230, 230, 307, 409, 512, 614, 768, 614, 512, 409, 307, 230, 230, 230]


def decode_msadpcm(wav: bytes):
    """RIFF MS-ADPCM (or 16-bit PCM) -> (float32 array (n, channels) in -1..1, sample rate)"""
    i = 12
    fmt = data = None
    while i + 8 <= len(wav):
        cid, ln = wav[i:i + 4], struct.unpack_from("<I", wav, i + 4)[0]
        if cid == b"fmt ":
            fmt = wav[i + 8:i + 8 + ln]
        elif cid == b"data":
            data = wav[i + 8:i + 8 + ln]
        i += 8 + ln + (ln & 1)
    if fmt is None or data is None:
        raise ValueError("not a WAV")
    tag, ch, rate, _, align, bits = struct.unpack_from("<HHIIHH", fmt, 0)
    if tag == 1 and bits == 16:
        a = np.frombuffer(data[:len(data) // (2 * ch) * 2 * ch], "<i2").reshape(-1, ch)
        return a.astype(np.float32) / 32768.0, rate
    if tag != 2:
        raise ValueError(f"unsupported WAV format {tag}")
    spb, ncoef = struct.unpack_from("<HH", fmt, 18)
    coefs = [struct.unpack_from("<hh", fmt, 22 + 4 * k) for k in range(ncoef)]
    nblocks = len(data) // align
    out = np.zeros((nblocks * spb, ch), np.int16)
    pos = 0
    for b in range(nblocks):
        blk = data[b * align:(b + 1) * align]
        p = 0
        pred = list(blk[p:p + ch])
        p += ch
        delta = list(struct.unpack_from(f"<{ch}h", blk, p))
        p += 2 * ch
        s1 = list(struct.unpack_from(f"<{ch}h", blk, p))
        p += 2 * ch
        s2 = list(struct.unpack_from(f"<{ch}h", blk, p))
        p += 2 * ch
        c1 = [coefs[min(x, ncoef - 1)][0] for x in pred]
        c2 = [coefs[min(x, ncoef - 1)][1] for x in pred]
        for c in range(ch):
            out[pos, c] = s2[c]
            out[pos + 1, c] = s1[c]
        n = pos + 2
        c = 0
        for byte in blk[p:]:
            for nib in (byte >> 4, byte & 0x0F):
                sn = nib - 16 if nib & 8 else nib
                v = (s1[c] * c1[c] + s2[c] * c2[c]) // 256 + sn * delta[c]
                v = -32768 if v < -32768 else 32767 if v > 32767 else v
                s2[c], s1[c] = s1[c], v
                d = ADAPT[nib] * delta[c] // 256
                delta[c] = d if d >= 16 else 16
                if n < len(out):
                    out[n, c] = v
                c += 1
                if c == ch:
                    c = 0
                    n += 1
        pos += spb
    return out.astype(np.float32) / 32768.0, rate


COEFS = [(256, 0), (512, -256), (0, 0), (192, 64), (240, 0), (460, -208), (392, -232)]
RATE = 48000
SPB = 128                         # samples per block, as the game's voice lines (block align 70 bytes, mono)


def encode_msadpcm(pcm, rate=RATE, spb=SPB):
    """mono float (-1..1) or int16 samples at `rate` -> RIFF MS-ADPCM WAV bytes like the game's voice lines.
    Blocks are independent, so all blocks are encoded at once (numpy) and each block takes the predictor that
    reproduces it best."""
    x = np.asarray(pcm)
    if x.ndim == 2:
        x = x.mean(axis=1)
    if x.dtype.kind == "f":
        x = np.clip(np.round(x * 32767.0), -32768, 32767)
    x = x.astype(np.int64)
    nb = max(1, -(-len(x) // spb))
    x = np.concatenate([x, np.zeros(nb * spb - len(x), np.int64)]).reshape(nb, spb)
    adapt = np.array(ADAPT, np.int64)
    best = None
    for p, (c1, c2) in enumerate(COEFS):
        s2, s1 = x[:, 0].copy(), x[:, 1].copy()
        guess = (s1 * c1 + s2 * c2) >> 8
        delta = np.maximum(16, np.abs(x[:, 2] - guess) // 2)
        delta0 = delta.copy()
        nibs = np.zeros((nb, spb - 2), np.int64)
        err = np.zeros(nb, np.int64)
        for k in range(2, spb):
            pred = (s1 * c1 + s2 * c2) >> 8
            e = x[:, k] - pred
            n = np.clip(np.floor(e / delta + 0.5), -8, 7).astype(np.int64)
            v = np.clip(pred + n * delta, -32768, 32767)
            err += (x[:, k] - v) ** 2
            s2, s1 = s1, v
            delta = np.maximum(16, (adapt[n & 15] * delta) >> 8)
            nibs[:, k - 2] = n & 15
        if best is None:
            best = [np.zeros(nb, np.int64), delta0, nibs, err]
        else:
            m = err < best[3]
            best[0][m] = p
            best[1][m] = delta0[m]
            best[2][m] = nibs[m]
            best[3][m] = err[m]
    pred, delta0, nibs = best[0], np.minimum(best[1], 32767), best[2]
    head = np.zeros((nb, 7), np.uint8)
    head[:, 0] = pred
    head[:, 1:3] = delta0.astype("<i2").view(np.uint8).reshape(nb, 2)
    head[:, 3:5] = x[:, 1].astype("<i2").view(np.uint8).reshape(nb, 2)
    head[:, 5:7] = x[:, 0].astype("<i2").view(np.uint8).reshape(nb, 2)
    body = ((nibs[:, 0::2] << 4) | nibs[:, 1::2]).astype(np.uint8)
    data = np.concatenate([head, body], axis=1).tobytes()
    align = 7 + (spb - 2) // 2
    fmt = struct.pack("<HHIIHHHHH", 2, 1, rate, rate * align // spb, align, 4, 32, spb, len(COEFS))
    fmt += b"".join(struct.pack("<hh", a, b) for a, b in COEFS)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + body


def read_wav(data: bytes):
    """any RIFF WAV (PCM 8/16/24/32-bit, float, extensible, MS-ADPCM) -> (float32 (n, channels), rate)"""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    i, fmt, raw = 12, None, None
    while i + 8 <= len(data):
        cid, ln = data[i:i + 4], struct.unpack_from("<I", data, i + 4)[0]
        if cid == b"fmt ":
            fmt = data[i + 8:i + 8 + ln]
        elif cid == b"data":
            raw = data[i + 8:i + 8 + ln]
        i += 8 + ln + (ln & 1)
    if fmt is None or raw is None:
        raise ValueError("WAV without fmt / data")
    tag, ch, rate, _, align, bits = struct.unpack_from("<HHIIHH", fmt, 0)
    if tag == 0xFFFE and len(fmt) >= 26:
        tag = struct.unpack_from("<H", fmt, 24)[0]
    if tag == 2:
        return decode_msadpcm(data)
    ch = max(1, ch)
    if tag == 3:
        a = np.frombuffer(raw[:len(raw) // (4 * ch) * 4 * ch], "<f4" if bits == 32 else "<f8").reshape(-1, ch)
        return a.astype(np.float32), rate
    if tag != 1:
        raise ValueError(f"unsupported WAV encoding {tag} (save it as PCM WAV)")
    w = bits // 8
    n = len(raw) // (w * ch)
    b = np.frombuffer(raw[:n * w * ch], np.uint8).reshape(n * ch, w)
    if w == 1:
        a = (b[:, 0].astype(np.float32) - 128.0) / 128.0
    else:
        v = np.zeros(n * ch, np.int64)
        for k in range(w):
            v |= b[:, k].astype(np.int64) << (8 * k)
        sign = 1 << (8 * w - 1)
        v = (v ^ sign) - sign
        a = v.astype(np.float32) / float(sign)
    return a.reshape(n, ch), rate


def load_audio(path):
    """an audio file -> (mono float32, rate).  WAV and .vag are read directly; other formats (mp3, ogg, flac, m4a ...)
    through ffmpeg when it is installed."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] == b"RIFF":
        a, rate = read_wav(data)
    elif path.lower().endswith(".vag"):
        a, rate = decode_msadpcm(sound.parse_se(data)["wav"])
    else:
        import shutil
        import subprocess
        import tempfile
        exe = shutil.which("ffmpeg")
        if not exe:
            raise RuntimeError("Only WAV files can be read without ffmpeg.  Save the recording as .wav, or install "
                               "ffmpeg (and add it to PATH) to import MP3 / OGG / FLAC / M4A.")
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "a.wav")
            subprocess.run([exe, "-y", "-v", "error", "-i", path, "-vn", "-ac", "1", "-c:a", "pcm_s16le", out],
                           check=True, capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            with open(out, "rb") as f:
                a, rate = read_wav(f.read())
    a = a.mean(axis=1) if a.ndim == 2 else a
    return a.astype(np.float32), int(rate)


def resample(a, rate, to=RATE):
    if rate == to or not len(a):
        return a
    try:
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(int(rate), int(to))
        return resample_poly(a, to // g, rate // g).astype(np.float32)
    except ImportError:
        t = np.arange(int(len(a) * to / rate)) * (rate / to)
        return np.interp(t, np.arange(len(a)), a).astype(np.float32)


def make_vag(a, rate, normalize=True, trim=True):
    """mono float samples -> a voice line file (.vag: the game's 28-byte header + MS-ADPCM WAV, 48 kHz)"""
    a = resample(np.asarray(a, np.float32), rate)
    if trim and len(a):
        loud = np.nonzero(np.abs(a) > 0.004 * max(1e-4, float(np.abs(a).max())) / 0.1)[0]
        if len(loud):
            a = a[max(0, loud[0] - RATE // 50): loud[-1] + RATE // 8]
    if normalize and len(a):
        peak = float(np.abs(a).max())
        if peak > 1e-4:
            a = a * (0.89 / peak)                 # about -1 dB, like the game's lines
    return sound.build_se(encode_msadpcm(a, RATE), RATE)


class SoundBank:
    """sound effects by number, decoded on first use (cached)"""

    def __init__(self, data_dir):
        path = os.path.join(data_dir, ARCHIVE)
        self.pack = sound.PsfsPack(path) if os.path.exists(path) else None
        self.cache = {}

    def has(self, sid):
        return self.pack is not None and f"{int(sid):04d}.vag" in self.pack.by_name

    def get(self, sid):
        """(mono float32 array, rate) or None"""
        sid = int(sid)
        if sid not in self.cache:
            pcm = None
            if self.has(sid):
                try:
                    se = sound.parse_se(self.pack.read(f"{sid:04d}.vag"))
                    a, rate = decode_msadpcm(se["wav"])
                    pcm = (a.mean(axis=1) if a.ndim == 2 else a, rate)
                except (ValueError, struct.error):
                    pcm = None
            self.cache[sid] = pcm
        return self.cache[sid]


# ------------------------------------------------------------------------------------------------ voices
def VoiceBank(fs, mods=(), lang="EN", get=None):
    """voice lines for the previews: d5lib.voices.VoiceBank"""
    from .voices import VoiceBank as _VB
    return _VB(fs, mods, lang, get)
