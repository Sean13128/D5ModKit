"""Another character's own skill in the caster's own look (Henna, Seraphina ... with Killia's Macrocosm).

Some skills show their user through stand-in actors whose look depends on who casts it: the scripts test the caster's
sprite number ($62199, see scalepatch.script_sprite_patch).  Macrocosm hides the caster and plays an event-pose Killia
(`cmd_6402 1001, 7000` when $62199 == 10) and the awakened Killia (`cmd_6402 1002, 20`) in his place; Seraphina's
skills spawn her event poses the same way.  Anyone else casting it (a new character like Henna, sprite 14560, or
another of the game's characters) matched none of the branches: the stand-ins got no look, the hidden caster stayed
hidden, and the caster vanished for most of the skill.

Such a skill gets one copy of its choreography for every caster but its own character (fork_texts; event ids
15800000 + ..., a block of 1000 per choreography):
* the branches of the skill's own character run ($62199 == 10 becomes $62199 != 0: always true; != 10 becomes
  == 0);
* in those branches the stand-ins take the caster's own look -- `cmd_6410 actor, 1256`: "look like the caster", as
  447 of the game's own scripts make their stand-ins (its colours too).  Tested in game 2026-10-14: `cmd_6402 actor,
  $62199` (the caster's sprite number) left Henna invisible -- and the owner's voice lines (cmd_4621-4623 play one
  exact line of the owner's voice bank: inside the branches or not, Seraphina's skills play hers anywhere) are left
  out; the caster's own lines (voice_play_actor) stay;
* poses only the owner's sprites have, played on those stand-ins, become poses every sprite has (generic_motion):
  the event-pose sheet's animations (8000 and up) the standing pose, the owner's own poses (7000 and up) and the
  special-pose stubs (motions 150-154, which go on with the sprite's own 7001-7041) an attack or the cast pose.
The skill's wrapper (12000000 + skill) plays the copy when $62199 is none of the numbers the skill tests, the original
otherwise.  The install (fork_all) makes the copy for every such skill a character other than its own learns; the
skill editor previews the same copy (fork_events) for any caster but the skill's own character.
"""
import re

from . import database, script

SKILL_SCRIPT = 12000000
FORK_BASE, FORK_END = 15800000, 15900000       # no game event and no kit custom choreography uses these
VAR = "$62199"
LOOKS = ("cmd_6402", "cmd_6405")               # give an extra actor the look of a class / a sprite
CASTER_LOOK = 1256                             # cmd_6410 source: mode 0, actor 1256 = like the caster
OWNER_VOICES = ("cmd_4621", "cmd_4622", "cmd_4623")
POSE_ANIM_MIN = 8000                           # event-pose sheets' animations (8501 ...)
OWN_POSE_MIN = 7000                            # a character's own special poses (7001 ...: only its sprite has them)
# motions 150-154 (animations 1501-1547) are stubs that go on with the sprite's own pose 7001-7041: a sprite
# without it shows nothing (Thunderlady in Macrocosm's 1521; Seraphina has no 7041) -> a pose every sprite has
SPECIAL_MOTIONS = {150: 101, 151: 109, 152: 101, 153: 101, 154: 101}
GENERIC_ATTACK, STAND = 101, 0


def generic_motion(anim=None, motion=None):
    """the pose every sprite has for an animation / motion only some sprites have, else None"""
    if anim is not None:
        a = abs(anim)
        if a >= POSE_ANIM_MIN:
            return STAND
        if a >= OWN_POSE_MIN:
            return GENERIC_ATTACK
        return SPECIAL_MOTIONS.get(a // 10)
    if motion >= OWN_POSE_MIN:
        return GENERIC_ATTACK
    return SPECIAL_MOTIONS.get(motion)
REF_RE = re.compile(r"^\s*(?:call_event|spawn_event|call_event_b)\s+(\d+)")
TEST_RE = re.compile(r"\$62199 (==|!=) (\d+)")
LABEL_RE = re.compile(r"^\s*(\w+):\s*$")


def _is_choreo(e):
    from .skills import is_choreo
    return is_choreo(e)


def lines_of(ev):
    return [l for l in script.disassemble_event(ev, comments=False) if l.strip() and not l.startswith("event ")]


def refs(ev):
    return [i.args[0] for i in ev.code if i.cid in (0x0100, 0x0104, 0x0106) and isinstance(i.args[0], int)]


def root_of(events, skill):
    """the choreography root a skill's wrapper plays (None: no wrapper / no choreography)"""
    w = events.get(SKILL_SCRIPT + int(skill))
    if w is None:
        return None
    return next((r for r in refs(w) if _is_choreo(r)), None)


def tree(events, root):
    out, todo = [], [int(root)]
    while todo:
        e = todo.pop(0)
        if e in out or e not in events:
            continue
        out.append(e)
        todo += [r for r in refs(events[e]) if _is_choreo(r)]
    return out


def tested(events, eids):
    """the sprite numbers the events test $62199 against"""
    out = set()
    for e in eids:
        for l in lines_of(events[e]):
            if l.lstrip().startswith("if ") and VAR in l:
                out.update(int(m.group(2)) for m in TEST_RE.finditer(l))
    return out


def owner_sprite(skill, root, values, magic, sprites):
    """the sprite number of the character whose skill this is, among the tested ones: its user's (magic.dat user1),
    else the user's of another skill playing the same choreography (a kit copy: 'New skill of their own').
    sprites: {class: sprite} of the game's characters.  None: a skill of no one in particular (Star, Heal: their
    branches pick poses per class, and others take the default)"""
    user = magic.get(int(skill), {}).get("user1", 0)
    u = sprites.get(user)
    if u in values:
        return u
    for sid, row in magic.items():
        if row.get("root") == root and sprites.get(row.get("user1", 0)) in values:
            return sprites[row["user1"]]
    if not user or user in sprites:
        return None
    # a mod's own skill playing a game character's choreography: the first character it singles out
    uniques = {v for c, v in sprites.items() if 0 < c < 1000}
    hits = sorted(v for v in values if v in uniques)
    return hits[0] if hits else None


def _args(st):
    name, _, rest = st.partition(" ")
    return name, [a.strip() for a in rest.split(",")] if rest.strip() else []


def fork_texts(events, eids, mapping, owner):
    """{new event id: text} of the copies of `eids` (mapping old -> new) played by any caster but the skill's own
    character (its sprite number `owner`)"""
    own = str(owner)

    def is_mine(st):
        return st.startswith("if ") and any(m.group(1) == "==" and m.group(2) == own for m in TEST_RE.finditer(st))
    looked = set()
    for e in eids:                                     # pass 1: the actors the owner's branches give a look to
        mine = set()
        for l in lines_of(events[e]):
            st = l.strip()
            if is_mine(st):
                mine.add(st.rsplit(" else ", 1)[1])
            elif LABEL_RE.match(l):
                mine.discard(LABEL_RE.match(l).group(1))
            elif mine:
                name, args = _args(st)
                if name in LOOKS and args:
                    looked.add(args[0])
    texts = {}
    for e in eids:                                     # pass 2: the copies
        out, mine = [], set()
        for l in lines_of(events[e]):
            st = l.strip()
            ind = l[:len(l) - len(l.lstrip())]
            lab = LABEL_RE.match(l)
            if st.startswith("if ") and VAR in st:
                if is_mine(st):
                    mine.add(st.rsplit(" else ", 1)[1])
                new = TEST_RE.sub(lambda m: (f"{VAR} != 0" if m.group(1) == "==" else f"{VAR} == 0")
                                  if m.group(2) == own else m.group(0), st)
                out.append(ind + new)
                continue
            if lab:
                mine.discard(lab.group(1))
                out.append(l)
                continue
            name, args = _args(st)
            if mine and name in LOOKS and len(args) >= 2:
                out.append(f"{ind}cmd_6410 {args[0]}, {CASTER_LOOK}")      # look like the caster
                continue
            if name in OWNER_VOICES:                   # (a line of the owner's voice bank, anywhere in the skill)
                continue
            if name in ("cmd_6500", "cmd_6510") and len(args) >= 2 and args[0] in looked \
                    and args[1].lstrip("-").isdigit():
                g = generic_motion(anim=int(args[1])) if name == "cmd_6500" else generic_motion(motion=int(args[1]))
                if g is not None:
                    blend = args[2] if name == "cmd_6510" and len(args) > 2 else "0"
                    out.append(f"{ind}cmd_6510 {args[0]}, {g}, {blend}")
                    continue
            m = REF_RE.match(l)
            if m and int(m.group(1)) in mapping:
                l = l.replace(m.group(1), str(mapping[int(m.group(1))]), 1)
            out.append(l)
        texts[mapping[e]] = f"event {mapping[e]}\n" + "\n".join(out) + "\n"
    return texts


def wrapper_text(events, wrapper_id, root, fork_root, values):
    """the wrapper playing the original root when the caster's sprite is one the skill tests (`values`), the copy
    otherwise"""
    out = []
    k = 0
    vals = sorted(values)
    for l in lines_of(events[wrapper_id]):
        m = REF_RE.match(l)
        if not (m and int(m.group(1)) == int(root)):
            out.append(l)
            continue
        ind = l[:len(l) - len(l.lstrip())]
        other = " and ".join(f"({VAR} != {v})" for v in vals)
        own = " or ".join(f"({VAR} == {v})" for v in vals)
        out += [f"{ind}if {other} else LSI{k + 1}", ind + "  " + l.strip().replace(m.group(1), str(fork_root), 1),
                f"{ind}endif", f"  LSI{k + 1}:",
                f"{ind}if {own} else LSI{k + 2}", ind + "  " + l.strip(), f"{ind}endif", f"  LSI{k + 2}:"]
        k += 2
    return f"event {wrapper_id}\n" + "\n".join(out) + "\n"


def skill_owner(events, skill, root, magic, sprites):
    """(owner sprite, tested values) of a skill that singles out its own character, else None"""
    if not root:
        return None
    vals = tested(events, tree(events, root))
    if not vals:
        return None
    own = owner_sprite(skill, root, vals, magic, sprites)
    return (own, vals) if own is not None else None


def fork_events(events, root, owner, base=FORK_BASE):
    """{new id: Event} of the copy of a choreography for any caster but its own character (the skill editor's
    preview) -> (events, new root)"""
    eids = tree(events, root)
    mapping = {e: base + i for i, e in enumerate(eids)}
    out = {}
    for nid, text in fork_texts(events, eids, mapping, owner).items():
        lines = [l.strip() for l in text.splitlines()[1:] if l.strip()]
        out[nid] = script.assemble_event(nid, lines)
    return out, mapping[int(root)]


def _blocks(used):
    b = FORK_BASE
    while b < FORK_END:
        if not any(b <= e < b + 1000 for e in used):
            yield b
        b += 1000


def learned(char_table, outfit_ids=()):
    """{skill: [(class, sprite)]} of every row's learned skills (outfit copies left out: their scripts see their
    character's sprite)"""
    out = {}
    for r in char_table.rows:
        if r["id"] in outfit_ids:
            continue
        for k in range(1, 17):
            sk = int(r[f"learn{k}_skill"])
            if sk:
                out.setdefault(sk, []).append((int(r["id"]), int(r["sprite_id"])))
    return out


def fork_all(sf, char_table, magic_table, vanilla_char, outfit_ids=(), log=print):
    """the install step: a copy of every skill that singles out its own character and that someone else learns ->
    number of copies"""
    from . import scriptpatch
    events = {e.id: e for e in reversed(sf.events)}           # (the game takes the first event of an id)
    magic, names = {}, {}
    for r in magic_table.rows:
        if int(r["id"]) not in magic:
            magic[int(r["id"])] = {"user1": int(r["user1"]), "root": root_of(events, r["id"])}
            names[int(r["id"])] = r["name_EN"] or str(r["id"])
    sprites = {r["id"]: int(r["sprite_id"]) for r in vanilla_char.rows}
    rows = {}
    for r in char_table.rows:
        rows.setdefault(r["id"], r)
    texts, roots, done = {}, {}, []
    blocks = _blocks(set(events))
    for sk, users in sorted(learned(char_table, outfit_ids).items()):
        root = magic.get(sk, {}).get("root")
        info = skill_owner(events, sk, root, magic, sprites)
        if info is None:
            continue
        own, vals = info
        others = [c for c, s in users if s not in vals]
        w = SKILL_SCRIPT + sk
        if not others or w not in events:
            continue
        if root not in roots:
            base = next(blocks)
            eids = tree(events, root)
            mapping = {e: base + i for i, e in enumerate(eids)}
            texts.update(fork_texts(events, eids, mapping, own))
            roots[root] = mapping[root]
        texts[w] = wrapper_text(events, w, root, roots[root], vals)
        done.append((names.get(sk, str(sk)), sorted({rows[c]["name_EN"] for c in others if c in rows})))
    if not done:
        return 0
    scriptpatch.apply(sf, {"events": texts})
    log("  stand-ins (another character's own skill in the caster's own look): " +
        "; ".join(f"{n} ({', '.join(w[:4])}{' …' if len(w) > 4 else ''})" for n, w in done))
    return len(roots)


def _candidates(char_table, magic_table, vanilla_char, outfit_ids):
    """does a character learn a skill of another character?  (script.dat is parsed only then: it takes seconds)"""
    users = {}
    for r in magic_table.rows:
        users.setdefault(int(r["id"]), int(r["user1"]))
    for sk, who in learned(char_table, outfit_ids).items():
        u = users.get(sk, 0)
        if u and any(c != u for c, _ in who):
            return True
    return False


def _finalize(ctx):
    from .skills import SCRIPT
    char_vp = "Database/Database_0.dat/char.dat"
    magic_vp = "Database/Database_0.dat/magic.dat"
    try:
        t = database.load_table("char.dat", ctx.get(char_vp))
        mt = database.load_table("magic.dat", ctx.get(magic_vp))
        van = database.load_table("char.dat", ctx.fs.read(char_vp))
    except Exception as e:
        ctx.log(f"  stand-ins: skipped ({e})")
        return
    outfit_ids = {int(b) for _, b in getattr(ctx, "_outfit_pairs", [])}
    if not _candidates(t, mt, van, outfit_ids):
        return
    sf = ctx.parsed(SCRIPT, script.ScriptFile.from_bytes)
    if fork_all(sf, t, mt, van, outfit_ids, log=ctx.log):
        ctx.changed(SCRIPT, script.ScriptFile.to_bytes)


def _register():
    from .modsys import register_finalizer
    register_finalizer(_finalize)


_register()
