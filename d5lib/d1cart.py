"""Bounded Disgaea 1 Complete HD source reader (native Disgaea 5 ANM bodies).

D1 Complete's HD bodies are already Disgaea 5 ANM archives, so this reader parses them with
``d5lib.anm`` rather than the D2 compatibility adapter the historical Forge readers used. That
keeps mesh-node assembly and cell composition identical to the receiver.

Two source behaviours drive the pose plan and are recorded in every receipt:

* Monsters carry Disgaea 5's own monster action ids (1/7 stand, 11/17 walk, 1021 damage,
  2001 melee, 2011 secondary swing, 2021 chant, 2031 release, 2041 recovery), so their rows map
  straight onto the Kit's ``MONSTER_ROWS``.
* Generic humanoid bodies carry standing/guard animation only (6001/6007 wait, 7001 stance and a
  few single-frame stance variants). Their action rows are therefore *held poses* taken from the
  same body and disclosed as such; no attack or walk animation is invented.

No Forge module, installer, save or game-folder archive is read here.
"""
from __future__ import annotations

import contextlib
import functools
import hashlib
import json
from pathlib import Path

FORMAT = 'character-forge-d1complete-local/1'
MAX_MANIFEST = 8 * 1024 * 1024
MAX_BODY = 64 * 1024 * 1024

# source animation id -> builder row name. Empirical: verified by rendering the frames and
# inspecting them; no runtime consumer was exercised.
HUMAN_ROWS = {6001: 'wait', 7001: 'stand'}
# Rows a humanoid body cannot supply are held from these, and listed in the receipt.
HUMAN_HELD = {'walk': 'wait', 'dash': 'wait', 'damage': 'stand', 'launch': 'stand',
              'attack_fist': 'stand', 'attack_sword': 'stand', 'attack_lance': 'stand',
              'attack_arrow': 'stand', 'attack_gun': 'stand', 'attack_ax': 'stand',
              'two_arm_up_jump': 'stand', 'one_arm_up': 'stand', 'squat': 'stand',
              'take_out': 'stand', 'kabutowari': 'stand', 'landing': 'stand', 'rolling': 'stand'}
MONSTER_ROWS = {1: 'stand', 11: 'walk', 1001: 'wait', 1011: 'wait', 1051: 'wait',
                1021: 'damage', 1031: 'damage', 1061: 'damage', 1071: 'attack_fist',
                2001: 'attack_fist', 2011: 'attack_sword', 2021: 'one_arm_up',
                2031: 'two_arm_up_jump', 2041: 'kabutowari', 1501: 'squat', 1511: 'squat',
                1091: 'two_arm_up_jump', 1121: 'squat', 4001: 'one_arm_up'}
# The receiver's own required ordinary actions: front and back for each.
REQUIRED_ROWS = ('stand', 'wait', 'walk', 'damage', 'attack_fist')

# Bank 1 of the D1 Complete art dump is the game's *shared* motion set, authored against D5's own
# motion ids and re-bindable onto any body's art (`anm.bind_motion_set`).  Three slots are already
# taken from it by name -- 11/17 walk, 21/27 hurt (``shared_walk`` / ``shared_damage``) and 2671/2677
# lift (``shared_lift``).  The ordinary action rows below are the same set: an event-only body (Carter
# 2560, Fl:F.Angel 5390) carries stand and walk plus the shared bank, so the rows its own bank 0 does
# not contain come from bank 1 with this body's art, recorded per row in the receipt.  Each row lists
# its candidate id pairs in preference order because a bank animation that a body's cells cannot draw
# renders blank (1001/1007 is empty for every body measured, 1071 blank on 2560): the first pair that
# draws wins and the pair used is recorded.  This is opt-in (``shared_fallback``) because a body that
# should be refused must still be refused.
SHARED_ACTION_TAGS = {'stand': [(1, 7)],
                      'wait': [(1051, 1057), (1001, 1007), (1011, 1017)],
                      'walk': [(11, 17)],
                      'damage': [(1021, 1027), (1031, 1037), (1061, 1067)],
                      'attack_fist': [(1071, 1077), (2001, 2007), (2011, 2017)]}
POSES_SHARED_FALLBACK = False


@contextlib.contextmanager
def shared_fallback(enabled=True):
    """Enable the bank-1 fill for `poses` calls made inside this block (build_batch.prepare)."""
    global POSES_SHARED_FALLBACK
    previous = POSES_SHARED_FALLBACK
    POSES_SHARED_FALLBACK = bool(enabled)
    try:
        yield
    finally:
        POSES_SHARED_FALLBACK = previous


def _sha(data):
    return hashlib.sha256(data).hexdigest()


@functools.lru_cache(maxsize=4)
def _manifest(path, stamp):
    raw = Path(path).read_bytes()
    if not 0 < len(raw) <= MAX_MANIFEST:
        raise ValueError('Disgaea 1 Complete manifest outside its size bound')
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get('format') != FORMAT:
        raise ValueError('Not a Disgaea 1 Complete sprite dump')
    if not isinstance(data.get('characters'), list) or not isinstance(data.get('bodies'), dict):
        raise ValueError('Incomplete Disgaea 1 Complete sprite manifest')
    return data, _sha(raw)


def manifest(root):
    path = Path(root) / 'manifest.json'
    stat = path.stat()
    data, digest = _manifest(str(path), (stat.st_size, stat.st_mtime_ns))
    return data, digest


def characters(root):
    return manifest(root)[0]['characters']


def catalog(root):
    return {int(body): info for body, info in manifest(root)[0]['bodies'].items()}


def body_path(root, body):
    return Path(root) / f'bodies/anm{int(body):05d}.dat'


def body_bytes(root, body):
    """The exact body bytes, checked against the manifest's size and SHA256."""
    info = catalog(root)[int(body)]
    path = body_path(root, body)
    size = path.stat().st_size
    if not 32 <= size <= MAX_BODY or size != info['bytes']:
        raise ValueError(f'body {body} has an unexpected size')
    raw = path.read_bytes()
    if _sha(raw) != info['sha256']:
        raise ValueError(f'body {body} failed its integrity check')
    return raw


@functools.lru_cache(maxsize=8)
def _parsed(path, stamp, expected):
    from . import anm
    raw = Path(path).read_bytes()
    if _sha(raw) != expected:
        raise ValueError('Disgaea 1 Complete sprite body failed its integrity check')
    return anm.parse(raw)


def animation_ids(root, body):
    """{animation id: [(block, anim), ...]} for one verified body."""
    from . import anm
    info = catalog(root)[int(body)]
    path = body_path(root, body)
    stat = path.stat()
    data = _parsed(str(path), (stat.st_size, stat.st_mtime_ns), info['sha256'])
    ids = {}
    for bi, ai, anim in data.all_animations():
        ids.setdefault(anim.id, []).append((bi, ai))
    return ids


def body_info(root, body):
    """Palette/texture/animation counts of one verified body (no rendering)."""
    info = catalog(root)[int(body)]
    path = body_path(root, body)
    stat = path.stat()
    data = _parsed(str(path), (stat.st_size, stat.st_mtime_ns), info['sha256'])
    return dict(palettes=len(data.palettes), textures=len(data.textures),
                blocks=len(data.blocks), animations=len(data.all_animations()),
                animation_ids=sorted({a.id for _, _, a in data.all_animations()}))


def _rows_for(kind):
    if kind not in ('humanoid', 'monster'):
        raise ValueError('source body kind must be humanoid or monster')
    return HUMAN_ROWS if kind == 'humanoid' else MONSTER_ROWS


def _shared_row(root, body, row, tags, palette):
    """Render bank 1's motion ids `tags` ({'front': id, 'back': id}) with this body's art.

    The returned rows have a separate common canvas and pivot: a raised-arms lift or a walk
    stride extends beyond the ordinary body canvas. Callers must retain those bounds when
    placing the drawings. A present but invalid bank or blank frame is an error, never a
    silent fallback.
    """
    from . import anm
    body = int(body)
    if type(palette) is not int or not 0 <= palette < 10:
        raise ValueError('palette index must be 0..9')
    if 1 not in catalog(root):
        return None
    sprite_raw = body_bytes(root, body)
    bank_raw = body_bytes(root, 1)
    sprite = anm.parse(sprite_raw)
    if palette >= len(sprite.palettes):
        raise ValueError(f'body {body} has no palette {palette}')
    bank = anm.parse(bank_raw)
    view = anm.bind_motion_set(bank, 0, sprite)
    ids = {anim.id: (bi, ai) for bi, ai, anim in view.all_animations()}
    missing = [tag for tag in tags.values() if tag not in ids]
    if missing:
        raise ValueError(f'shared bank 1 lacks motion {missing}')
    frames = {}
    for direction in ('front', 'back'):
        index = ids[tags[direction]]
        frames[direction] = [(t, anm.evaluate(view, index, t)) for t in anm.frame_times(view, index)]
    bounds = anm.item_bounds([item for entries in frames.values() for _, draw in entries for item in draw])
    result, times = {}, {}
    for direction, entries in frames.items():
        result[(row, direction)] = []
        times[direction] = []
        for n, (t, draw) in enumerate(entries):
            image, _ = anm.render_items(view, draw, palette_index=palette, bounds=bounds,
                                        background=(0, 0, 0, 0))
            if image.getchannel('A').getextrema()[1] == 0:
                raise ValueError(f'body {body} shared {row} {direction} frame {n} is blank')
            result[(row, direction)].append(image)
            times[direction].append(t)
    return result, dict(body=body, body_sha256=_sha(sprite_raw), bank=1,
                        bank_sha256=_sha(bank_raw), row=row, source_tags=dict(tags),
                        bounds=list(bounds), row_times=times)


def shared_lift(root, body, *, palette=0):
    """Render bank 1's 2671/2677 with this body's art, or None if bank 1 is absent."""
    return _shared_row(root, body, 'launch', {'front': 2671, 'back': 2677}, palette)


def shared_walk(root, body, *, palette=0):
    """Render bank 1's 11/17 (the source game's walk) with this body's art, or None if absent.

    D5's own level-walk selection is 11/17 (decomp ``14052e920_turn_unit_auto_walk_step``), so the
    receiver's walk slot names the same thing the source does here; the ids agree by meaning, not by
    accident of numbering.
    """
    return _shared_row(root, body, 'walk', {'front': 11, 'back': 17}, palette)


def shared_damage(root, body, *, palette=0):
    """Render bank 1's 21/27 hurt reaction with this body's art, or None if bank 1 is absent.

    D5's hurt slot is pose base 2 (motions 21/27): script event 15092305 plays motion 21 on the
    target of a hit together with the impact effect, and the vanilla render is a standing flinch
    that recovers. The source's bank 1 carries the *same* id with the *same* seven-key timing
    (0/6/12/18/24/30/35) because D1 Complete's HD bodies were authored from the D5 motion set, so
    this is a same-id, same-length, same-meaning slot rather than a lookalike.
    """
    return _shared_row(root, body, 'damage', {'front': 21, 'back': 27}, palette)


def _shared_action_draws(root, sprite, rows):
    """Bank 1's ordinary-action ids bound onto `sprite`'s art -> ``{row: (tags, [(view, tag, t, draw)])}``.

    Same mechanism as ``_shared_row`` (bind_motion_set, this body's palettes and cells), but the
    caller renders with the body's own canvas so these rows line up with the rest of the pack.  A
    candidate pair whose first frame draws nothing (alpha == 0) is skipped: the bank's animation ids
    are shared, but the cells a body owns decide what can actually be drawn.
    """
    from . import anm
    if 1 not in catalog(root):
        raise ValueError('shared motion bank 1 is absent from this source dump')
    bank = anm.parse(body_bytes(root, 1))
    view = anm.bind_motion_set(bank, 0, sprite)
    ids = {anim.id: (bi, ai) for bi, ai, anim in view.all_animations()}
    out = {}
    for row in rows:
        chosen = None
        for front, back in SHARED_ACTION_TAGS[row]:
            if front not in ids or back not in ids:
                continue
            entries = []
            for direction, tag in (('front', front), ('back', back)):
                index = ids[tag]
                entries += [(direction, tag, t, anm.evaluate(view, index, t))
                            for t in anm.frame_times(view, index)]
            draws = [entry[3] for entry in entries]
            bounds = anm.item_bounds([item for draw in draws for item in draw])
            drawn = False
            for draw in draws:
                image, _ = anm.render_items(view, draw, bounds=bounds, background=(0, 0, 0, 0))
                if image.getchannel('A').getextrema()[1]:
                    drawn = True
                    break
            if not drawn:
                continue                                     # this body cannot draw that motion
            chosen = ({'front': front, 'back': back}, entries)
            break
        if chosen is None:
            raise ValueError(f'shared bank 1 has no drawable motion for row {row} of this body')
        out[row] = chosen
    return view, out


def poses(root, body, *, kind, palette=0, blank_frames='error', shared_fallback=None):
    """Render one verified body into builder rows, on one shared canvas.

    Returns ``(sequences, receipt)``. ``sequences`` is ``{(row, 'front'|'back'): [PIL images]}``
    where every image is a full canvas in one fixed bounds box, so frames from different source
    animations keep their relative position and the feet pivot. Rows a humanoid body cannot
    supply are filled by the declared held-pose rule, never by another body's art.

    ``blank_frames`` decides what a single empty frame inside an otherwise drawn animation
    means. ``'error'`` (default) refuses the body: a blank cell in the source set is not
    something this reader may silently invent around. ``'drop'`` keeps that cell out of the row
    and records it in the receipt, which is the honest option for a body whose own animation
    table contains an empty key (Vampire, body 2180, tag 1501 frame 5).

    ``shared_fallback`` (or the ``shared_fallback()`` block, when ``None``) lets a body that
    carries stand/walk only take its missing ordinary rows from the game's own shared motion bank
    (body 1, ``SHARED_ACTION_TAGS``) rendered with this body's art; each such row is recorded in
    ``receipt['shared_rows']``.  Off by default: a body that cannot supply the receiver's rows is
    still refused.
    """
    from . import anm
    body = int(body)
    if type(palette) is not int or not 0 <= palette < 10:
        raise ValueError('palette index must be 0..9')
    allow_shared = POSES_SHARED_FALLBACK if shared_fallback is None else bool(shared_fallback)
    raw = body_bytes(root, body)
    data = anm.parse(raw)
    if palette >= len(data.palettes):
        raise ValueError(f'body {body} has no palette {palette}')
    available = {}
    for bi, ai, anim in data.all_animations():
        available.setdefault(anim.id, []).append((bi, ai))

    table = _rows_for(kind)
    plan = {}                                     # (row, view) -> [(tag, block, anim)]
    unused = []
    for tag in sorted(available):
        base = tag - 6 if tag % 10 == 7 else tag
        row = table.get(base)
        if row is None:
            unused.append(tag)
            continue
        view = 'back' if tag % 10 == 7 else 'front'
        plan.setdefault((row, view), []).append((tag, *available[tag][0]))
    if not plan:
        raise ValueError(f'body {body} has no rows this reader can read (kind={kind})')

    # One bounds box for the whole body: renders line up with each other and with the pivot.
    frames = {}
    for key, entries in plan.items():
        tag, bi, ai = entries[0]
        times = anm.frame_times(data, (bi, ai))
        frames[key] = [(tag, n, t, anm.evaluate(data, (bi, ai), t)) for n, t in enumerate(times)]
    bounds = anm.item_bounds([item for poses_ in frames.values() for _, _, _, items in poses_ for item in items])
    # Rows the body's own bank does not carry at all: an event-only body (Carter 2560, Fl:F.Angel
    # 5390) has stand and walk and nothing else.  Refused by default; with the shared fallback the
    # gap comes from the source's own shared motion bank (body 1) with this body's art.
    gap = [(row, view) for row in REQUIRED_ROWS for view in ('front', 'back')
           if (row, view) not in frames
           and row not in (HUMAN_HELD if kind == 'humanoid' else ())
           and not (kind == 'humanoid' and row == 'stand')]
    shared_view = shared_draws = None
    if gap:
        if not allow_shared:
            raise ValueError(f'body {body} cannot supply the receiver-required rows: {gap}')
        shared_view, shared_draws = _shared_action_draws(root, data, dict.fromkeys(row for row, _ in gap))
        extra = anm.item_bounds([item for _tags, rows in shared_draws.values() for *_, draw in rows
                                 for item in draw])
        bounds = (min(bounds[0], extra[0]), min(bounds[1], extra[1]),
                  max(bounds[2], extra[2]), max(bounds[3], extra[3]))
    sequences, evidence, row_times = {}, [], {}
    origins = set()
    dropped = []
    for key, items in frames.items():
        images = []
        for tag, n, t, draw in items:
            image, origin = anm.render_items(data, draw, palette_index=palette, bounds=bounds,
                                             background=(0, 0, 0, 0))
            if image.getchannel('A').getextrema()[1] == 0:
                if blank_frames != 'drop':
                    raise ValueError(f'body {body} tag {tag} frame {n} is blank')
                dropped.append(dict(row=key[0], view=key[1], tag=tag, frame=n, time=t))
                continue
            images.append(image)
            origins.add(origin)
            evidence.append(dict(row=key[0], view=key[1], tag=tag, frame=n, time=t,
                                 canvas=list(image.size)))
        sequences[key] = images
        row_times[f'{key[0]}_{key[1]}'] = [
            tt for (tg, nn, tt, _) in items
            if not any(d['tag'] == tg and d['frame'] == nn and d['time'] == tt for d in dropped)]

    held = []
    if kind == 'humanoid':
        for view in ('front', 'back'):
            if ('stand', view) not in sequences and ('wait', view) in sequences:
                sequences[('stand', view)] = sequences[('wait', view)][:1]
                held.append(dict(row='stand', view=view, held_from='wait',
                                 reason='body has no separate stance animation'))
        for row, source in HUMAN_HELD.items():
            for view in ('front', 'back'):
                if (row, view) in sequences:
                    continue
                used = next((name for name in (source, 'stand', 'wait')
                             if (name, view) in sequences), None)
                if used is None:
                    continue
                frames_from = sequences[(used, view)]
                # A walk is held by repeating the standing drawing; an action row holds one frame.
                sequences[(row, view)] = list(frames_from) if row in ('walk', 'dash') else frames_from[:1]
                held.append(dict(row=row, view=view, held_from=used,
                                 reason='D1 Complete HD humanoid art carries standing/guard animation only'))
    shared_rows = []
    if shared_draws and shared_view is not None:
        bank_sha = _sha(body_bytes(root, 1))
        for row, (tags, entries) in shared_draws.items():
            for view in ('front', 'back'):
                keys = [entry for entry in entries if entry[0] == view]
                if not keys:
                    continue
                images, times = [], []
                for direction, tag, t, draw in keys:
                    image, origin = anm.render_items(shared_view, draw, palette_index=palette,
                                                     bounds=bounds, background=(0, 0, 0, 0))
                    if image.getchannel('A').getextrema()[1] == 0:
                        # Same policy as the body's own rows: a blank cell inside a shared motion is
                        # refused unless the caller asked for `drop`, and then it is recorded.
                        n = len(images)
                        if blank_frames != 'drop':
                            raise ValueError(f'body {body} shared bank {row} {view} is blank')
                        dropped.append(dict(row=row, view=view, tag=tag, frame=n, time=t, bank=1))
                        continue
                    images.append(image)
                    times.append(t)
                    origins.add(origin)
                    evidence.append(dict(row=row, view=view, tag=tag, time=t,
                                         canvas=list(image.size), bank=1))
                sequences[(row, view)] = images
                row_times[f'{row}_{view}'] = times
                shared_rows.append(dict(row=row, view=view, tags=dict(tags),
                                        bank=1, bank_sha256=bank_sha,
                                        row_times=list(times), frames=len(images),
                                        reason=('the body carries stand/walk only: this row is the source '
                                                'game\'s own shared motion bank rendered with this body art')))
    missing = [(row, view) for row in REQUIRED_ROWS for view in ('front', 'back')
               if (row, view) not in sequences]
    if missing:
        raise ValueError(f'body {body} cannot supply the receiver-required rows: {missing}')
    receipt = dict(
        schema='d1c-body-read/1', body=body, kind=kind, palette=palette,
        body_sha256=_sha(raw), body_bytes=len(raw),
        canvas=dict(bounds=list(bounds), width=int(bounds[2] - bounds[0]),
                    height=int(bounds[3] - bounds[1]), distinct_origins=[list(o) for o in sorted(origins)]),
        rows={f'{row}_{view}': len(images) for (row, view), images in sorted(sequences.items())},
        row_times=row_times,
        source_tags=sorted(available), unassigned_tags=sorted(unused),
        held_pose_rows=held, dropped_blank_frames=dropped,
        shared_rows=shared_rows,
        native_animation_count=len(available),
        limitations=["Frames are the source's own drawings; receiver timing is transferred from the "
                     "source animation length (ownanim source_times), not from its exact key spacing.",
                     'Held rows repeat a standing frame and are not authored action animation.']
                    + (['Rows listed in shared_rows come from the source shared motion bank (body 1) '
                        'rendered with this body art: the body itself carries stand/walk only.'] if shared_rows else []))
    return sequences, receipt
