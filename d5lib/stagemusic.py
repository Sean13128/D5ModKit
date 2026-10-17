"""A stage's battle music and what makes a stage run: its talk.dat stage triggers.  (Found in game 2026-10-16.)

When a battle starts, event 11 enters the map and runs `talk_b 0, -1, 1`: the first talk.dat record with talk id 0,
key2 = the map number and key3 = the phase (1 = battle start) whose flag conditions hold.  The plain record (no
flags_on: what every visit after the story uses) is

    record talk=0 key2=101 key3=1 on=- off=2201
      flag_off 2200
      script 300101
      end

and the game's stages all have a start event 300000 + map number of one line, `call_event 300010, <song x 10>`;
300010 sets up the battle and plays the song (`bgm_play_b $20001, 100`): Dried Up Wasteland's 120 plays BGM 12.
Phase 3 (back from the battle) runs `script 14` (the stage list's music) and may set the story flag of the next
stage.  A map with no records gets no battle start at all: the music of the stage list goes on.

So a stage's battle music = the argument of its start event (any track the game has, or a mod's new one), and a
new stage needs trigger records of its own: copies of its base stage's plain ones, pointing at its own start event,
without the flags that would unlock the base stage's story.
"""
import re

from . import script, talk

START_BASE = 300000            # a stage's start event: 300000 + map number
BATTLE_SETUP = 300010          # sets the battle up and plays the song it is given (x 10)
SONG_SCALE = 10


def start_event(map_id):
    return START_BASE + int(map_id)


def start_text(map_id, song):
    """the start event of a stage that plays `song` (a music file number) when the battle starts"""
    return (f"event {start_event(map_id)}\n    call_event {BATTLE_SETUP}, {int(song) * SONG_SCALE}\n"
            f"    wait_children_c\n    wait_children\n")


def song_of(ev):
    """the song a start event plays (its call_event 300010 argument / 10), or None"""
    if ev is None or not ev.code:
        return None
    for ins in ev.code:
        if ins.cid in (0x0104, 0x0106) and ins.args and ins.args[0] == BATTLE_SETUP and len(ins.args) > 1 \
                and isinstance(ins.args[1], int):
            return ins.args[1] // SONG_SCALE
    return None


def song_in_text(text):
    m = re.search(r"call_event\s+%d\s*,\s*(\d+)" % BATTLE_SETUP, text or "")
    return int(m.group(1)) // SONG_SCALE if m else None


def effective_song(sf, mods, map_id):
    """the battle song of a stage: the last enabled mod's start event for it, else the game's"""
    eid = str(start_event(map_id))
    for m in reversed(list(mods)):
        p = m.load_patch("script", "script.json") or {}
        if eid in (p.get("events") or {}):
            return song_in_text(p["events"][eid])
    for ev in sf.events:
        if ev.id == start_event(map_id):
            return song_of(ev)
    return None


def set_song(mod, map_id, song):
    """the stage's start event in `mod` plays `song` (None: the mod's own start event is removed, the game's or
    another mod's plays again)"""
    p = mod.load_patch("script", "script.json") or {}
    ev = dict(p.get("events") or {})
    key = str(start_event(map_id))
    if song is None:
        ev.pop(key, None)
    else:
        ev[key] = start_text(map_id, song)
    mod.save_patch("script", "script.json", {"events": ev} if ev else None)


# ------------------------------------------------------------------------------------------------ stage triggers
STORY_FLAGS = range(5000, 6000)        # the stage list's story flags (dungeon.dat +0x16): never set by a copy


def plain_triggers(tf, map_id):
    """the stage's trigger records without story conditions (what plays on any visit after the story)"""
    return [r for r in tf.records if r.talk_id == 0 and r.key2 == int(map_id) and not r.flags_on]


def trigger_texts(tf, base_map, new_map):
    """talk.dat records for a new stage: its base stage's plain triggers moved to the new map, their start event
    the new stage's, without story flags (they would unlock the base stage's next stage); the game's defaults when
    the base has none"""
    from .textpatch import record_text
    out = []
    for r in plain_triggers(tf, base_map):
        t = record_text(tf, r)
        lines = t.splitlines()
        lines[0] = re.sub(r"\bkey2=\d+", f"key2={int(new_map)}", lines[0])
        body = []
        for ln in lines[1:]:
            m = re.match(r"\s*flag_on\s+(\d+)\s*$", ln)
            if m and int(m.group(1)) in STORY_FLAGS:
                continue
            body.append(re.sub(r"\bscript\s+%d\b" % start_event(base_map), f"script {start_event(new_map)}", ln))
        out.append("\n".join([lines[0]] + body) + "\n")
    if not out:
        out = [f"record talk=0 key2={int(new_map)} key3=1 on=- off=2201\n  flag_off 2200\n"
               f"  script {start_event(new_map)}\n  end\n",
               f"record talk=0 key2={int(new_map)} key3=3 on=- off=2202\n  flag_off 2200\n  script 14\n  end\n"]
    return out


def add_triggers(mod, texts):
    p = mod.load_patch("text", "talk.json") or {}
    added = list(p.get("added") or [])
    added += texts
    p["added"] = added
    mod.save_patch("text", "talk.json", p)


def move_stage(mod, old_map, new_map):
    """a mod's stage renumbered: its trigger records and its start event follow"""
    p = mod.load_patch("text", "talk.json") or {}
    added = []
    for t in p.get("added") or []:
        head, _, rest = t.partition("\n")
        if re.search(r"\btalk=0\b", head) and re.search(r"\bkey2=%d\b" % int(old_map), head):
            head = re.sub(r"\bkey2=\d+", f"key2={int(new_map)}", head)
            rest = re.sub(r"\bscript\s+%d\b" % start_event(old_map), f"script {start_event(new_map)}", rest)
        added.append(head + "\n" + rest)
    if p.get("added"):
        p["added"] = added
        mod.save_patch("text", "talk.json", p)
    s = mod.load_patch("script", "script.json") or {}
    ev = dict(s.get("events") or {})
    old = ev.pop(str(start_event(old_map)), None)
    if old is not None:
        ev[str(start_event(new_map))] = re.sub(r"^event\s+\d+", f"event {start_event(new_map)}", old)
        mod.save_patch("script", "script.json", {"events": ev})
