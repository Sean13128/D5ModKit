"""Songs in and out of the game's music format without extra programs (libsndfile through the soundfile package;
ffmpeg is used when it is installed and a file needs it, e.g. .m4a).

The game plays a track's intro once, then its loop part over and over (d5lib.sound: one member = two Ogg Vorbis
streams, 48 kHz stereo).  A song becomes a track by cutting it at two points: everything before the loop start is the
intro, loop start to loop end is the part that repeats.  Pick the points on the beat (the same place in two bars) so
the jump back can't be heard; the editor's 'hear the join' plays the seconds around it.

    pcm, rate = read_audio("song.mp3")            # float32 (samples, channels)
    intro, loop = split(pcm, rate, 12.5, 98.25)    # seconds
    track = sound.build_track(encode_ogg(loop, rate), encode_ogg(intro, rate) if len(intro) else b"")
"""
import io
import os
import shutil
import subprocess
import tempfile

import numpy as np

RATE = 48000                      # the game's music: 48 kHz stereo Ogg Vorbis
QUALITY = 0.35                    # libsndfile compression level for Vorbis (0 = best; 0.35 ~ ffmpeg -q:a 6.5)


def soundfile():
    try:
        import soundfile as sf
        return sf
    except Exception:
        return None


def ffmpeg():
    return shutil.which("ffmpeg")


def can_read(path):
    ext = os.path.splitext(path)[1].lower()
    return bool(soundfile()) and ext in (".wav", ".flac", ".ogg", ".oga", ".mp3", ".aif", ".aiff") or bool(ffmpeg())


def read_audio(path):
    """(float32 array (n, channels), rate) of an audio file"""
    sf = soundfile()
    if sf is not None:
        try:
            data, rate = sf.read(path, dtype="float32", always_2d=True)
            return data, rate
        except Exception:
            if not ffmpeg():
                raise
    exe = ffmpeg()
    if not exe:
        raise RuntimeError(f"{os.path.basename(path)} can't be read: use WAV, FLAC, OGG or MP3 (or install ffmpeg "
                           "for other formats).")
    out = tempfile.mktemp(suffix=".wav")
    try:
        subprocess.run([exe, "-y", "-i", path, "-vn", "-ar", str(RATE), "-ac", "2", "-c:a", "pcm_f32le", out],
                       check=True, capture_output=True)
        import wave  # noqa: F401  (float WAV: read with soundfile when there, else numpy)
        if sf is not None:
            data, rate = sf.read(out, dtype="float32", always_2d=True)
            return data, rate
        return _read_f32_wav(out)
    finally:
        if os.path.exists(out):
            os.remove(out)


def _read_f32_wav(path):
    raw = open(path, "rb").read()
    i = raw.find(b"fmt ")
    ch = int.from_bytes(raw[i + 10:i + 12], "little")
    rate = int.from_bytes(raw[i + 12:i + 16], "little")
    j = raw.find(b"data")
    n = int.from_bytes(raw[j + 4:j + 8], "little")
    return np.frombuffer(raw[j + 8:j + 8 + n], "<f4").reshape(-1, ch).copy(), rate


def read_ogg(data):
    """(float32 (n, channels), rate) of Ogg Vorbis bytes (one stream of a game track)"""
    sf = soundfile()
    if sf is None:
        raise RuntimeError("the soundfile package is missing (pip install soundfile)")
    pcm, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    return pcm, rate


def to_game(pcm, rate):
    """48 kHz stereo"""
    if pcm.shape[1] == 1:
        pcm = np.repeat(pcm, 2, axis=1)
    elif pcm.shape[1] > 2:
        pcm = pcm[:, :2]
    if rate != RATE:
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(int(rate), RATE)
        pcm = resample_poly(pcm, RATE // g, int(rate) // g, axis=0).astype(np.float32)
    return np.clip(pcm, -1.0, 1.0)


def split(pcm, rate, loop_start, loop_end=None):
    """(intro, loop) of a song cut at two times in seconds (loop_end None: the end of the song)"""
    a = max(0, min(len(pcm), int(round(loop_start * rate))))
    b = len(pcm) if loop_end is None else max(a + 1, min(len(pcm), int(round(loop_end * rate))))
    return pcm[:a], pcm[a:b]


def encode_ogg(pcm, rate):
    """Ogg Vorbis bytes, 48 kHz stereo, as the game's tracks"""
    sf = soundfile()
    pcm = to_game(np.asarray(pcm, np.float32), rate)
    if sf is not None:
        buf = io.BytesIO()
        try:
            f = sf.SoundFile(buf, "w", RATE, 2, format="OGG", subtype="VORBIS", compression_level=QUALITY)
        except TypeError:                                   # (older soundfile without compression_level)
            f = sf.SoundFile(buf, "w", RATE, 2, format="OGG", subtype="VORBIS")
        with f:
            # small writes: libsndfile's Vorbis encoder puts a whole write on the stack (a song in one call
            # overflowed it and closed the program)
            for k in range(0, len(pcm), 8192):
                f.write(pcm[k:k + 8192])
        return buf.getvalue()
    exe = ffmpeg()
    if not exe:
        raise RuntimeError("Converting to the game's format needs the soundfile package or ffmpeg.")
    src, out = tempfile.mktemp(suffix=".wav"), tempfile.mktemp(suffix=".ogg")
    try:
        write_wav(src, pcm, RATE)
        subprocess.run([exe, "-y", "-i", src, "-c:a", "libvorbis", "-q:a", "6", out], check=True, capture_output=True)
        return open(out, "rb").read()
    finally:
        for p in (src, out):
            if os.path.exists(p):
                os.remove(p)


def write_wav(path, pcm, rate):
    """16-bit WAV (any audio editor opens it)"""
    import wave
    pcm = np.asarray(pcm, np.float32)
    if pcm.ndim == 1:
        pcm = pcm[:, None]
    data = (np.clip(pcm, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(data.tobytes())


def track_parts(track):
    """(intro pcm, loop pcm, rate) of a game track (d5lib.sound member bytes)"""
    from . import sound
    t = sound.parse_track(track)
    loop, rate = read_ogg(t["loop"])
    intro = read_ogg(t["intro"])[0] if t["intro"] else np.zeros((0, loop.shape[1]), np.float32)
    return intro, loop, rate


def export_track(track, path_wav, loops=1):
    """the track as a WAV (intro, then the loop `loops` times) plus its parts as plain .ogg files and the loop
    point -> {'wav', 'intro', 'loop', 'notes', 'loop_start' (seconds)}"""
    from . import sound
    t = sound.parse_track(track)
    intro, loop, rate = track_parts(track)
    write_wav(path_wav, np.concatenate([intro] + [loop] * max(1, loops)), rate)
    base = os.path.splitext(path_wav)[0]
    out = {"wav": path_wav, "loop_start": len(intro) / rate, "loop_end": (len(intro) + len(loop)) / rate}
    if t["intro"]:
        out["intro"] = base + " intro.ogg"
        open(out["intro"], "wb").write(t["intro"])
    out["loop"] = base + " loop.ogg"
    open(out["loop"], "wb").write(t["loop"])
    out["notes"] = base + " loop points.txt"
    with open(out["notes"], "w", encoding="utf-8") as f:
        f.write(f"{os.path.basename(path_wav)}\n\n"
                f"Intro: 0.000 s to {out['loop_start']:.3f} s ({len(intro)} samples at {rate} Hz), played once.\n"
                f"Loop:  {out['loop_start']:.3f} s to {out['loop_end']:.3f} s ({len(loop)} samples), played over and "
                f"over after the intro.\n\nTo use an edited version in the D5 Mod Kit: Music & Sound > Replace with "
                f"my song, set 'Loop starts at' to {out['loop_start']:.3f} and 'Loop ends at' to "
                f"{out['loop_end']:.3f}.\n")
    return out


def peaks(pcm, width):
    """(mins, maxs) of the mono mix in `width` columns: a waveform picture"""
    mono = pcm.mean(axis=1) if pcm.ndim == 2 else pcm
    if not len(mono):
        return np.zeros(width), np.zeros(width)
    edges = np.linspace(0, len(mono), width + 1).astype(np.int64)
    lo = np.array([mono[a:b].min() if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])])
    hi = np.array([mono[a:b].max() if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])])
    return lo, hi
