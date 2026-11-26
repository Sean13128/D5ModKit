"""The runtime's animation trace and actor probe lines (d5lib/native/d5anmtrace.inc.c) as dicts.

d5auto.log carries them as "HH:MM:SS.mmm [anmtrace] <event> key=value ..." and "... [actorprobe] <event> ...":
    [anmtrace] state mode=guard lookup=1 bank=1 setup=1 create=1 seek=1     (after every anmtrace on/guard/off)
    [anmtrace] skip hook=setup rva=0x14E7E0 reason=prologue
    [anmtrace] miss id=643 caller=0x3ffce1                                  (anm_find_loaded_slot found no bank)
    [anmtrace] bank id=643 flag=0 arg=1 slot=-1 caller=0x14e853             (anm_acquire_lzs)
    [anmtrace] setup actor=0x... slot=12 anim=643 palette=0 motion=1007 kind=1 alt=645 sign=1 caller=0x...
    [anmtrace] create actor=0x... slot=12 anim=643 palette=0 motion=1007 kind=1 caller=0x...
    [anmtrace] nullseek owner=0x... player=0x... group=643 motion=1007 palette=0 frame=12 guard=1 caller=0x...
    [anmtrace] cap lines=4000
    [actorprobe] start slot=12 frames=60
    [actorprobe] sample slot=12 frame=12991 n=0 anm=643 ... tick=3211264 ... rec=643 npal=1 ntex=2 motion=1007

    for d in anmtrace.read(GAME_DIR / "d5auto.log"): ...      # {"src", "event", "time", <keys>}

Numbers become ints (hex too); "none" stays a string.  An actorprobe sample also gets "tick_frames" (tick / 65536).
"""
import re

LINE = re.compile(r"^(?:(\d\d:\d\d:\d\d\.\d{3}) )?\[(anmtrace|actorprobe|voicetrace)\] (\w+)(.*)$")


def _value(v):
    try:
        return int(v, 0)
    except ValueError:
        return v


def parse_line(line):
    """one log line -> dict, or None when it is not an anmtrace / actorprobe line"""
    m = LINE.match(line.strip())
    if not m:
        return None
    t, src, event, rest = m.groups()
    d = {"src": src, "event": event, "time": t}
    for w in rest.split():
        k, _, v = w.partition("=")
        d[k] = _value(v)
    if src == "actorprobe" and isinstance(d.get("tick"), int):
        d["tick_frames"] = d["tick"] / 65536.0
    return d


def parse(text):
    return [d for d in map(parse_line, text.splitlines()) if d]


def read(path, src=None, event=None):
    """every trace / probe line of a log file (optionally only one src / event)"""
    with open(path, encoding="utf-8", errors="replace") as f:
        out = parse(f.read())
    return [d for d in out if (src is None or d["src"] == src) and (event is None or d["event"] == event)]


VOICE_PLAY_CALLER = 0x3F7954        # return address of sound_voice_play's own table lookup (VOICE2)


def voice_requests(path):
    """Every voice line the game asked to play while `voicetrace on` (d5anmtrace.inc.c): [{"time", "line", "set",
    "kind", "voice_id", "personality", "n"}].  line = set * 1000 + n; set = kind * 100000 + voice id * 10 + personality."""
    out = []
    for d in read(path, src="voicetrace", event="lookup"):
        if d.get("caller") == VOICE_PLAY_CALLER:
            s = d["set"]
            out.append(dict(time=d["time"], line=d["line"], set=s, kind=s // 100000, voice_id=s % 100000 // 10,
                            personality=s % 10, n=d["line"] % 1000))
    return out


def voice_clip(mod_dir, line, lang="JP"):
    """The clip file a custom-voice line id plays, from the pack that defines the voice (None when it is not one of
    the pack's lines): the readback half of `voice_requests`."""
    from . import modsys, voices
    data = voices.load(modsys.Mod(str(mod_dir)))
    vid = str(line // 1000 % 100000 // 10)
    if vid not in data["voices"]:
        return None
    for ln, (kind, ref) in voices.custom_lines(int(vid), data["voices"][vid], lang=lang):
        if ln.id == line:
            return dict(file=ref if kind == "file" else None, source=kind, situations=ln.cats, kind=ln.group // 100000)
    return None
