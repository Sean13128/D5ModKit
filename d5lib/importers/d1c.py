"""Disgaea 1 Complete importer: one class of the import command (IMPORTCORE-INTERFACE.md).

Roster: ``d1c-roster.json`` (297 census rows, 64 listings: 47 buildable = 22 ``ready`` + 22 ``medium`` + 3
``hard``, 17 already in D5; ids, leases and rules only, names as SHA-256 references).  Everything is read from the
user's verified prepared source folder (``data/SUBDATA.DAT`` through ``_d1c_source``; SOURCEPREP4-D1C); nothing
here invents data.

What it wraps (unchanged logic, called per entry; ``_d1c_batch`` carries what the Research batch scripts did):

  * ``_d1c_batch.build_class``          13 classes: 2 humanoid + 11 monster, registry families
  * ``_d1c_batch.build_unique``         the 22 ``ready`` and 22 ``medium`` uniques (recorded leases and
                                        donors in ``d1c-roster.json``, medium donors chosen by the measured
                                        height probe, same single-rank build path)
  * ``d5lib/nativeimports.build_entry`` the builder both of those call
  * ``tools/hurtslot1_build.transform`` HURTSLOT1's reaction-slot remap (committed on this line)

and adds the two things the batch scripts did not do:

  * **Source faces** from ``start.dat[73]`` (D1CFACE1, by sprite id) and **authored cut-ins** from the
    Switch ``start.dat[98]`` pack (see ``d1c_art``).
    The installed D1C banks carry a face and a cut-in *derived from the standing sprite*, because
    "D1C HD has no busts" was believed; D1CCUTIN1 disproved it.  A rebuild carries the authored
    picture through the same kit writers.
  * **The later fix passes** run on every built pack, so they cannot be forgotten:
    the PALMERGE/PALFIX2B palette rule (the rebuilt bank carries the installed bank's palette
    and image-header counts, checked for equality by the ``wheel_freeze`` gate) and the
    HURTSLOT1 hurt-slot remap.  D1CPAL1 makes that a build-time property instead of a check the
    build could fail: a unique whose installed bank is one of the 34 that carry the graft's second
    palette group (offset 10) and its extra atlas page is built with exactly that shape
    (``_receiver_shape`` -> ``nativeimports.build_entry(sprite_shape=...)`` ->
    ``ownanim.build(shape=...)``), so the source atlas is packed over the receiver's page count and
    the installer's banner repack is a no-op.  A pack with no installed copy builds naturally.

Fix passes that are *not* here, with the reason: PALFIX2B's banner pre-repack exists to make a
graft layout match the installed header counts; a fresh build is checked against the same counts by
the ``wheel_freeze`` gate instead of being forced into TEST28's layout.

CORED1CB closed the one real regression: the hurt slot.  ``_install_hurt_source`` runs before any
build and does what D1CMOTION2's ``--shared-damage`` rebuild did, but inside the normal build: the
builder's ``prepare`` gains the source's bank-1 hurt reaction as an explicit ``dmgsrc`` row
(``tools/pt1030_rebuild_d1c.add_shared_damage`` -> ``d5lib.d1cart.shared_damage``, seven source
frames at D5's own 0/6/12/18/24/30/35), and ``build_entry`` receives its key times as
``source_times``.  ``d5lib.ownanim`` then binds those frames to the pack's 21/27 slot and keeps the
donor's old held picture as 65003/65004, so stub aliases do not start flinching.  That is the
honest rebuild CORED1C listed as option 2: 21/27 come out of the source, not out of a preserved
bank, and HURTSLOT1's reaction-slot remap then has something to remap.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import threading
from pathlib import Path

from . import _d1c_batch, _d1c_source, d1c_art

# SOURCEPREP4-D1C: no machine path, no Research/ tree and no installed pack on the default path.  The only
# game file is the verified prepared SUBDATA.DAT (``_d1c_source``); the roster, leases, donors and skill
# ladders are ``d1c-roster.json``, the installed banks' counts are ``d1c-bank-shapes.json`` (ids/counts, text
# as SHA-256 references).  ``--installed-reference`` is the explicit, read-only opt-in that compares with a pack.
BANK_DIR = Path('files/Anime/ANM_HI_JP.dat')
MAP = Path(__file__).resolve().parents[1] / 'sourcemaps/d1c.json'
# D1CFIX3: uniques whose donor hovers (Sea Angel etc.) but whose source body stands on the ground: Priere,
# Marjoly, Don Joaquin, Lamington.  Measured source stand foot +11..+13 vs the built -7/-8.
# Second batch (same cause, same rule: shared stand/walk animations moved by one rigid donor-pivot shift):
# Ghoss 2901, Gargo 2902, Manty 2903, Maderas 2550, Thursday 2200, Antoire 3050.
# D1CFIX4 (Sean 2026-11-18, web-checked): Dark Flonne's sprite wears palette 2 (red bow). Her
# character-table palette byte is 0 (D1CFIX3 piece 1), so the sprite default colour is forced here.
# Sprite only: the cut-in keeps d1c_art.PALETTE_OVERRIDES.
SPRITE_PALETTE_OVERRIDES = {3060: 2}
GROUND_TO_SOURCE = {3000, 3010, 2600, 2580, 2901, 2902, 2903, 2550, 2200, 3050}


def unique_rows(names=True):
    """The listing rows with the ROSTERGAP1 overrides applied (name/title read from the source character table;
    ``names=False`` gives the ids and rules without opening a game file)."""
    return _d1c_batch.unique_rows(names)


def unique_leases():
    """Recorded leases plus the ones measured for the roster gap (ids only)."""
    return _d1c_batch.unique_leases()


def skill_map():
    """The reviewed D1C unique skill map (d5lib/sourcemaps/d1c.json, tools/d1c_unique_skillmap.py)."""
    return json.loads(MAP.read_text())['characters']


def unique_learn(listing):
    """[[D5 skill id, learn level], ...] for one D1C unique: the map's rows that name a twin, first row wins per id."""
    seen, out = set(), []
    for r in (skill_map().get(str(listing)) or {}).get('skills', []):
        if r.get('d5_id') and r['d5_id'] not in seen and len(out) < 16:
            seen.add(r['d5_id'])
            out.append([int(r['d5_id']), int(r['level'])])
    return out


def help_line3(listing):
    """Honest charhelp line 3 from the map's labels, replacing the batch builder's "N D1 abilities use D5 same-effect skills"."""
    rows = [r for r in (skill_map().get(str(listing)) or {}).get('skills', []) if r.get('d5_id')]
    if not rows:
        return None
    if all(r['label'] == 'donor' for r in rows):
        return 'No D1 skills; D5 donor-class skills'
    n = {k: sum(1 for r in rows if r['label'] == k) for k in ('exact', 'adapted', 'donor')}
    return f"{len(rows)} D1 skills -> D5: " + ', '.join(f'{v} {k}' for k, v in n.items() if v)


def _fix_help_line3(mod, listing):
    text = help_line3(listing)
    path = Path(mod) / 'patches/db/charhelp.dat.json'
    if text and path.is_file():
        doc = json.loads(path.read_text())
        for row in doc.get('added') or []:
            for lang in ('JP', 'EN', 'FR', 'CHN', 'KOR'):
                if 'D1 abilities use D5 same-effect skills' in str(row.get(f'line3_{lang}')):
                    row[f'line3_{lang}'] = text
        path.write_text(json.dumps(doc, indent=1, ensure_ascii=False))


DONOR_EVILITIES = Path(__file__).with_name('d1c-donor-evilities.json')


def _d5_text():
    """Resolver for the D5 strings the donor table names (D5 tables only: no D1C source needed)."""
    from .. import textrefs
    if _d1c_batch.GAME and _d1c_batch.STATE:
        return textrefs.d5_text_pool(_d1c_batch.GAME, _d1c_batch.STATE).get
    return textrefs.d5_text_pool_for_build().get


def donor_evilities(mod_folder=None, text=None):
    """The donor table (or one row) with its ``@text`` references resolved from the Disgaea 5 tables.

    TEXTHASH-D1C-DD2: the checked-in file stores only SHA-256 references for the donor and evility
    names/text, so this build-time read is where the strings come from the user's own game.  ``text``
    is an explicit resolver (a maintainer tool or a test); the default is the D1C build pool, which
    needs :func:`_d1c_batch.configure`, and otherwise the kit's own game/state resolver."""
    from .. import textrefs
    doc = json.loads(DONOR_EVILITIES.read_text())
    if mod_folder is not None:
        pick = doc['mods'].get(mod_folder)
        if pick is None or not textrefs.has_refs(pick):
            return pick
        if text is None:
            text = _d5_text()
        return textrefs.resolve(pick, text, f'd1c-donor-evilities.mods.{mod_folder}')
    if not textrefs.has_refs(doc):
        return doc
    if text is None:
        text = _d5_text()
    return textrefs.resolve_doc(doc, text, 'd1c-donor-evilities')


def apply_donor_evility(pack, mod_folder, table=None, text=None):
    """D1CEVIL1: D1C has no evilities, so the pack's char rows get a vanilla D5 DONOR evility.

    Sets evility1/evility_count on every char row of the pack (6 rank rows for a class, 1 for a unique)
    and labels it ``signature_evility: donor`` in mod.json.  Table: ``d1c-donor-evilities.json``
    (tools/build_d1c_donor_evilities.py).  Nothing else in the pack changes."""
    if table is not None:
        pick = table['mods'].get(mod_folder)
    else:
        pick = donor_evilities(mod_folder, text)
    if pick is None:
        return 'no donor evility for ' + mod_folder
    pack = Path(pack)
    cj = pack / 'patches/db/char.dat.json'
    doc = json.loads(cj.read_text())
    for row in doc['added']:
        row.update(evility1=pick['evility_id'], evility2=0, evility3=0, evility4=0, evility_count=1)
    cj.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    mj = pack / 'mod.json'
    meta = json.loads(mj.read_text())
    meta['source_import']['signature_evility'] = 'donor'
    meta['source_import']['signature_evility_donor'] = {
        k: pick[k] for k in ('donor_name', 'donor_char_id', 'evility_id', 'evility_name', 'rung', 'confidence')}
    mj.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    return f"donor evility {pick['evility_id']} {pick['evility_name']} (from {pick['donor_name']}, rung {pick['rung']})"

class Importer:
    game = 'd1c'

    def __init__(self, kit=None):
        self.kit = Path(kit) if kit else Path(__file__).resolve().parents[2]
        if str(self.kit) not in sys.path:
            sys.path.insert(0, str(self.kit))
        self._cache = {}
        self._ctx = {}

    # ------------------------------------------------------------------ the verified input / references
    def _use_source(self, source_root=None):
        """Resolve the verified prepared D1C input once (``source_root`` is an unverified diagnostic root)."""
        key = str(source_root or '')
        if self._cache.get('source_key') != key or 'source' not in self._cache:
            self._cache['source'] = _d1c_source.data(source_root or None)
            self._cache['source_key'] = key
        _d1c_source.use(self._cache['source'])
        return self._cache['source']

    def _reference_pack(self, mod_folder):
        """The installed pack of this name, only when the caller asked for an installed reference."""
        ctx = self._ctx or {}
        root = ctx.get('installed_root')
        if not (ctx.get('installed_reference') and root):
            return None
        path = Path(root) / Path(mod_folder).name
        return path if path.is_dir() else None

    @staticmethod
    def _recorded(mod_folder):
        """Recorded bank counts / hurt flag of the pack (``d1c-bank-shapes.json``), or {}."""
        return _d1c_source.rules('bank-shapes')['packs'].get(Path(mod_folder).name) or {}

    def wheel_reference(self, folder):
        """{member under files/: (textures, palettes)} of the pack's banks: the recorded freeze reference."""
        banks = self._recorded(folder).get('banks') or {}
        return {f'Anime/ANM_HI_JP.dat/{name}': tuple(v) for name, v in banks.items()}

    # ------------------------------------------------------------------ modules / source data
    def mods(self):
        """The builders (``_d1c_batch``; one module since SOURCEPREP4-D1C, so bb/ub/mb are the same object)."""
        if 'bb' not in self._cache:
            os.environ.setdefault('D5_KIT', str(self.kit))
            self._cache.update(bb=_d1c_batch, ub=_d1c_batch, mb=_d1c_batch)
        return self._cache

    def source_ref(self, row=None):
        ref = dict(file=_d1c_source.LABEL,
                   member='start.dat[98] (art) + start.dat[43] (character table)')
        ref['sha256'] = _d1c_source.sha256_of_source()
        if row is not None:
            ref['row'] = row
        return ref

    # ------------------------------------------------------------------ roster
    def roster(self, source_root=None) -> list[dict]:
        self._use_source(source_root)
        classes = dict(classes=_d1c_batch.class_specs(donor_names=False))
        census = dict(rows=range(_d1c_batch.roster_doc()['census_rows']))
        out = []
        for spec in classes['classes']:
            out.append(dict(id=f"class:{spec['registry']}", kind='class', name=spec['name'],
                            mod_folder=f"D1C_Class_{spec['registry']}",
                            source_ref=self.source_ref(dict(registry=spec['registry'],
                                                            character_id=spec['character_id'])),
                            in_scope=True, why_not=None,
                            detail=dict(registry=spec['registry'], character_id=spec['character_id'],
                                        physical=spec['physical'], template=spec['template'],
                                        shape=spec['kind'])))
        for row in unique_rows():
            if row['disposition'] != 'buildable-unique' and row['feasibility'] == 'no build':
                continue
            buildable = row['feasibility'] in ('ready', 'medium')
            out.append(dict(id=f"unique:{row['id']}", kind='unique', name=row['name'],
                            mod_folder=f"D1C_Unique_{row['id']}",
                            source_ref=self.source_ref(dict(listing=row['id'], body=row['body'],
                                                            census_rows=len(census.get('rows', [])))),
                            in_scope=buildable,
                            why_not=None if buildable else
                            ('object/prop body: no character or monster action rows, needs an object '
                             'recipe that does not exist yet (UNIQUES.md)'),
                            detail=dict(listing=row['id'], body=row['body'], shape=row['shape'],
                                        feasibility=row['feasibility'])))
        return out

    # ------------------------------------------------------------------ the source hurt reaction
    def _install_hurt_source(self, log=None):
        """Make every build emit the source's 21/27 hurt reaction (CORED1CB, Gap 1).

        Wraps, unchanged: ``tools/pt1030_rebuild_d1c.add_shared_damage`` (the D1CMOTION2
        ``--shared-damage`` row adder) around the builder's own ``prepare``, and passes the
        resulting ``row_times`` to ``nativeimports.build_entry(source_times=...)`` so
        ``d5lib.ownanim`` binds those frames to the hurt slot.  Idempotent per Importer.
        """
        if self._cache.get('hurt_installed'):
            return
        self.mods()
        sys.path.insert(0, str(self.kit / 'tools'))
        import pt1030_rebuild_d1c as adders
        bb = self._cache['bb']
        from d5lib import nativeimports
        orig_prepare, orig_build = bb.prepare, nativeimports.build_entry
        state = self._cache

        def prepare(spec, folder, _orig=orig_prepare):
            manifest, receipt = _orig(spec, folder)
            state['row_times'] = None
            if state.get('damage_disabled'):
                return manifest, receipt
            try:
                adders.add_shared_damage(spec, folder, manifest, receipt)
                state['row_times'] = receipt.get('row_times')
            except Exception as exc:                       # noqa: BLE001 - recorded, never hidden
                state['hurt_error'] = f'{type(exc).__name__}: {exc}'
                if log:
                    log(f'  hurt source unavailable for body {manifest.get("body")}: {exc}')
            return manifest, receipt

        def build_entry(*args, **kwargs):
            times = state.get('row_times')
            if times and kwargs.get('source_times') is None:
                kwargs['source_times'] = times
            shape = state.get('sprite_shape')
            if shape and kwargs.get('sprite_shape') is None:
                kwargs['sprite_shape'] = shape
            return orig_build(*args, **kwargs)

        bb.prepare = prepare
        nativeimports.build_entry = build_entry
        self._cache['hurt_installed'] = True

    # ------------------------------------------------------------------ build
    # One build at a time: the builders keep per-entry state in process globals (sprites.CACHE_DIR,
    # os.environ D5_OUT, the monkeypatched bb.prepare / nativeimports.build_entry and self._cache's
    # sprite_shape / row_times).  Under --jobs 2 the threads overwrote each other: class 11390 lost its
    # output cache ("actual cache must resolve to ..."), unique 2302 lost resident_ids.pickle, and unique
    # 2410 was built on another entry's receiver shape (10 palettes/4 textures instead of 20/2).
    _build_lock = threading.RLock()

    def build(self, entry, out_dir, ctx=None) -> dict:
        with self._build_lock:
            return self._build(entry, out_dir, ctx)

    def _build(self, entry, out_dir, ctx=None) -> dict:
        """Build one entry into ``<out_dir>/mods/<mod_folder>`` and return the interface Result."""
        ctx = dict(ctx or {})
        self._ctx = ctx
        self._use_source(ctx.get('source_root'))
        if ctx.get('game_path') is not None and ctx.get('state_root') is not None:
            _d1c_batch.configure(ctx['game_path'], ctx['state_root'])
        if not isinstance(entry, dict):                    # the shared runner passes an Entry
            entry = dict(id=entry.id, kind=entry.kind, name=entry.name,
                         mod_folder=entry.mod_folder, source_ref=entry.source_ref,
                         in_scope=entry.in_scope, detail=entry.detail)
        log = ctx.get('log') or (lambda *a: None)
        out_dir = Path(out_dir)
        mods_dir = out_dir / 'mods'
        mods_dir.mkdir(parents=True, exist_ok=True)
        work = Path(ctx.get('work') or (out_dir / '_work')) / entry['mod_folder']
        work.mkdir(parents=True, exist_ok=True)
        os.environ['D5_OUT'] = str(work)
        os.environ['D5_KIT'] = str(self.kit)

        result = dict(id=entry['id'], mod_folder=entry['mod_folder'], built=False, error=None,
                      gates={}, features={}, notes=[])
        try:
            self._install_hurt_source(log)
            self._cache['damage_disabled'] = self._installed_has_hurt(entry['mod_folder']) is False
            try:
                mod_path, meta = self._run_builder(entry, work, log)
            except ValueError as exc:
                if 'donor animation' not in str(exc):
                    raise
                # The donor template has no hurt slot to bind the source frames into (measured: the
                # D1C monster packs installed today carry no 21/27 at all).  Rebuild without the hurt
                # row and report the slot as not applicable instead of failing the entry.
                log(f'  no donor hurt slot for {entry["mod_folder"]}: {exc}')
                self._cache['damage_disabled'] = True
                result['notes'].append(f'hurt slot not applicable: {exc}')
                self._cache['hurt_na'] = True
                work_retry = work / 'no_hurt'
                work_retry.mkdir(parents=True, exist_ok=True)
                os.environ['D5_OUT'] = str(work_retry)
                mod_path, meta = self._run_builder(entry, work_retry, log)
                meta['hurt_na'] = True
                self._cache['damage_disabled'] = False
            target = mods_dir / entry['mod_folder']
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(mod_path), str(target))
            rig = self._source_rig(target, meta, (ctx.get('options') or {}).get('d1c_rig', 'auto'), log)
            meta.setdefault('notes', []).append(('source rig (D1CRIG1): ' + rig['note']) if rig.get('built')
                                                else ('flattened sprite path: ' + rig.get('why', '')))
            result['rig'] = {k: v for k, v in rig.items() if k != 'report'}
            result['notes'].append(apply_donor_evility(target, entry['mod_folder']))
            sprite_palette = SPRITE_PALETTE_OVERRIDES.get(int(meta.get('character_id') or 0),
                                                          meta.get('palette'))
            if meta['kind'] == 'unique' and sprite_palette:
                # D1CCOLOR1: the character table's palette byte is the unique's default colour
                from d5lib import anm, sourceimports
                for n in range(3):
                    f = target / 'files' / 'Anime' / 'ANM_HI_JP.dat' / f"anm{meta['physical'] + n:05d}.lzs"
                    a = anm.load(f)
                    if sourceimports.select_default_palette(a, sprite_palette):
                        raw = f.read_bytes()
                        out = a.to_bytes()
                        if raw[:4] in (b'dat\0', b'pac\0'):   # keep the member's storage form
                            from d5lib import lzs
                            out = anm.lzs_compress(out, lzs.header_ext(raw))
                        f.write_bytes(out)
            if not rig.get('built') and meta['kind'] == 'unique' and meta.get('character_id') in GROUND_TO_SOURCE:
                # D1CRIG1: a rig bank needs no grounding (every motion shares the source's one feet origin), which
                # covers the humanoid classes.  The monster class (Vampire 11930) is NOT grounded this way: measured,
                # align_to_source fixed its stand (-25 -> -3 px) but moved walk/idle from 36 px high to 33 px low
                # (one shared shift for animations whose donor tracks put the body at different heights).
                self._ground_to_source(target, meta, log)
            art = d1c_art.install_authored(
                target, kind=meta['kind'], target=meta['identity'], physical=meta['physical'],
                body=meta['body'], palette=meta.get('palette', 0), palettes=meta.get('palettes', 1),
                character_id=meta.get('character_id'), log=log,
                face_cutout=(ctx.get('options') or {}).get('d1c_faces') in ('cutout', 'hd-cutout'),
                face_source=('hd' if (ctx.get('options') or {}).get('d1c_faces', 'hd') in ('hd', 'hd-cutout')
                             else 'member73'),
                installed_pack=self._reference_pack(entry['mod_folder']))
            # HURTSLOT1 and BLANKKEYS1 repair a flattened bank (its reaction pages showed the held stand, its
            # resampled keys could draw nothing).  A rig bank plays D5's own reaction pages and key times on the
            # body's own pictures, so neither reason holds there: both passes are skipped for it.
            hurt = [] if rig.get('built') else self._hurt_slots(target, log)
            hold_info = {}
            held = (self._hold_blank_keys(target, log, hold_info)
                    if (ctx.get('options') or {}).get('d1c_hold_blank', True) and not rig.get('built') else {})
            result.update(built=True, notes=list(meta.get('notes', [])), mod_path=str(target))
            if held:
                result['hold_blank'] = held
                result['hold_blank_source'] = hold_info.get('source')
                result['notes'].append(
                    'blank key times held (BLANKKEYS1 rule, labelled approximation, '
                    + ('installed reference' if hold_info.get('source') == 'installed'
                       else 'held-blank-keys.json: no installed reference')
                    + '): ' + ', '.join(f'{b} {sorted(ids)}' for b, ids in held.items()))
            result['features'] = dict(
                stand='own', walk='own', attack='own', hurt='own',
                carried='adapted', stats='own',
                skills='adapted' if meta.get('skills') else 'missing',
                evilities='donor', voice='donor',
                specials='adapted' if meta.get('specials', True) else 'missing',
                ranks='own', recruit='own',
                face=('own' if art['face'] else
                      'fallback' if art.get('fallback') else 'adapted'),
                cutin='own' if art['cutin'] else 'adapted')
            block, cutin_fallback = d1c_art.resolve_block(
                meta['body'], meta.get('palette', 0), meta['character_id'])
            result['art'] = dict(faces=art['face'], cutins=art['cutin'], skipped=art['skipped'],
                                 source_face=art.get('source_face', {}),
                                 block=block, authored=d1c_art.has_cutin(block),
                                 cutin_fallback=cutin_fallback)
            result['hurt_slots'] = hurt
            meta['rig'] = bool(rig.get('built'))
            try:
                gates, counts = self._gates(target, entry, meta, art, hurt, block)
            except Exception as exc:                                   # noqa: BLE001 - reported
                gates, counts = {}, {}
                result['notes'].append(f'gate error: {type(exc).__name__}: {exc}')
            result['gates'] = gates
            result['bank_counts'] = counts
        except Exception as exc:                                       # noqa: BLE001 - reported
            import traceback
            result['error'] = f'{type(exc).__name__}: {exc}'
            result['trace'] = traceback.format_exc(limit=6)
        return result

    def _source_rig(self, target, meta, mode='auto', log=None):
        """D1CRIG1: replace the flattened sprite banks of a D1C block-1 humanoid by the source rig.

        The bank becomes the body's own sheets and palettes with D5's resident humanoid motions copied in
        (``d5lib.d1crig.build_bank``); the companion N+1 is the same bank under N+1, N+2 (the standing picture)
        is kept.  ``mode``: 'off' never, 'on' always (an ineligible body or a failed check raises), 'auto' when the
        body is eligible and every rig check passes (else the flattened banks stay and the reason is returned).
        -> {'built': bool, 'note' | 'why': str, 'report': {...}}"""
        from d5lib import anm, d1crig, gamefs, importcore, lzs, sprites
        if mode == 'off':
            return dict(built=False, why='d1c_rig off')
        cid, body_id, phys = int(meta.get('character_id') or 0), int(meta['body']), int(meta['physical'])
        log = log or (lambda *a: None)

        def refuse(why):
            if mode == 'on':
                raise ValueError(f'd1c_rig on: {why}')
            log(f'  rig not used: {why}')
            return dict(built=False, why=why)

        try:
            body = anm.parse(d1c_art.source().body_bytes(body_id))
        except Exception as exc:                           # noqa: BLE001 - reported
            return refuse(f'body {body_id} unreadable: {exc}')
        if _d1c_batch.GAME is None or _d1c_batch.STATE is None:
            return refuse('no Disgaea 5 install configured (the resident humanoid motions come from it)')
        from d5lib.d4unique import Originals
        fs = gamefs.GameFS(str(_d1c_batch.GAME), backup_resolver=Originals(_d1c_batch.STATE))
        try:
            motion = sprites.motion_block(fs, 1)
        finally:
            fs.reset()
        ok, why = d1crig.eligible(cid, body, motion)
        if not ok:
            return refuse(why)
        anime = target / BANK_DIR
        old = {n: (anime / f'anm{n:05d}.lzs').read_bytes() for n in (phys, phys + 1)
               if (anime / f'anm{n:05d}.lzs').is_file()}
        if phys not in old:
            return refuse(f'no built bank anm{phys:05d} to replace')
        report = {}
        bank = d1crig.build_bank(body, motion, phys, report=report)
        shapes = {}
        for n in (phys, phys + 1):
            out = bank if n == phys else anm.parse(bank.to_bytes())
            out.blocks[0].id = n
            raw = out.to_bytes()
            ref = old.get(n, old[phys])
            if ref[:4] in (b'dat\0', b'pac\0'):              # keep the member's storage form
                raw = anm.lzs_compress(raw, lzs.header_ext(ref))
            (anime / f'anm{n:05d}.lzs').write_bytes(raw)
            shapes[f'Anime/ANM_HI_JP.dat/anm{n:05d}.lzs'] = dict(
                textures=len(out.textures), palettes=len(out.palettes),
                pages=[[t.width, t.height] for t in out.textures],
                why=(f'D1CRIG1 source rig: body {body_id}\'s own {len(out.textures)} sheet page(s) and '
                     f'{len(body.palettes)} palette(s) (+{len(out.palettes) - len(body.palettes)} copies of '
                     'palette 0); owner approval and a live Hire-wheel check before install'))
        checks = {}
        for name, fn in (('idle_drawable', importcore.idle_drawable_gate), ('cell_pages', importcore.cell_page_gate),
                         ('render_root', importcore.render_root_gate),
                         ('palette_count', importcore.palette_count_gate)):
            checks[name] = fn(target)
        mj = target / 'mod.json'
        doc = json.loads(mj.read_text())
        si = doc.setdefault('source_import', {})
        sys.path.insert(0, str(self.kit / 'tools'))
        import d1c_motion_audit as audit
        si['d1c_rig'] = dict(report, motion_source="D5 anm_resident block 1, copied key for key",
                             body=body_id, character_id=cid)
        si['shape_changes'] = shapes
        mj.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
        pack = next((p for p in audit.d1c_packs(target.parent) if p['folder'] == target.name), None)
        if pack:
            pack['palette'] = 0        # a unique's default colour is swapped into slot 0 later (D1CCOLOR1): compare 0 with 0
        rows = audit.audit_pack(audit.Source(), pack) if pack else {}
        checks['source_motions'] = audit.gate(pack, rows) if pack else (False, 'pack not found by the audit')
        failed = {k: v[1] for k, v in checks.items() if not v[0]}
        if failed:
            for n, raw in old.items():                     # put the flattened banks back
                (anime / f'anm{n:05d}.lzs').write_bytes(raw)
            si.pop('d1c_rig', None)
            si.pop('shape_changes', None)
            mj.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
            return refuse('rig checks failed: ' + '; '.join(f'{k}: {v}' for k, v in failed.items()))
        si['adaptations'] = [a for a in si.get('adaptations') or []
                             if not a.startswith('Empirical source pose composition')] + [
            'Sprite: the D1C body\'s own sheets and palettes driven by D5\'s own humanoid motions (D1CRIG1); '
            f"{len(d1crig.D5_TO_D1C)} motions equal D1C's key for key, the rest are D5 motions on the body's "
            f"pictures; held stand for specials {report.get('held_specials')}"]
        si['d1c_rig']['audit'] = audit.summary(rows)
        mj.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
        counts = audit.summary(rows)
        note = (f"anm{phys:05d}/{phys + 1:05d} = body {body_id} sheets ({len(bank.textures)} pages, "
                f"{report['source_palettes']} source palettes) + {report['motions']} D5 motions; audit {counts}")
        log(f'  rig: {note}')
        return dict(built=True, note=note, report=report, audit=counts)

    def _ground_to_source(self, target, meta, log):
        """D1CFIX3: stand the body on the ground line the source drawing has (standground.align_to_source).

        Only the two main banks (physical, physical+1) move; physical+2 is the banner stand picture and is
        already on the ground."""
        from d5lib import anm, lzs, standground
        source = anm.parse(d1c_art.source().body_bytes(meta['body']))
        for n in range(2):
            f = target / 'files' / 'Anime' / 'ANM_HI_JP.dat' / f"anm{meta['physical'] + n:05d}.lzs"
            a = anm.load(f)
            moved = standground.align_to_source(a, source)
            log(f"  ground to source: anm{meta['physical'] + n:05d} {len(moved)} animations moved")
            if moved:
                raw = f.read_bytes()
                out = a.to_bytes()
                if raw[:4] in (b'dat\0', b'pac\0'):
                    out = anm.lzs_compress(out, lzs.header_ext(raw))
                f.write_bytes(out)

    def _run_builder(self, entry, work, log):
        m = self.mods()
        detail = entry['detail']
        self._cache['sprite_shape'] = None
        if entry['kind'] == 'class':
            bb = m['bb']
            spec = next(s for s in _d1c_batch.class_specs() if s['registry'] == detail['registry'])
            plan = _d1c_batch.skills_plan()[str(spec['registry'])]
            rows, table_sha = bb.table_rows()
            built = bb.build_class(spec, rows, table_sha, plan, work)
            body = next(c['body'] for c in d1c_art.source().characters()
                        if int(c['id']) == int(spec['character_id']))
            return (Path(built['result']['mod']),
                    dict(kind='class', identity=spec['registry'], physical=spec['physical'],
                         body=body, character_id=spec['character_id'], palette=0,
                         palettes=len(plan.get('palettes') or []) or 6,
                         skills=bool(plan.get('skills')), notes=['six ranks, registry family']))
        ub, mb = m['ub'], m['mb']
        listing = int(detail['listing'])
        row = next(r for r in unique_rows() if int(r['id']) == listing)
        leases = unique_leases()
        lease = leases.get(str(listing))
        if not lease:
            raise ValueError(f'{listing}: no recorded lease in unique-leases.json')
        table_rows, table_sha = m['bb'].table_rows()
        table_row = next(r for r in table_rows if r['id'] == listing)
        skill_doc = dict(skills=unique_learn(listing))
        donors = _d1c_batch.donor_rows()
        if listing in donors:
            donor_doc = donors[listing]
        else:                                    # the measured donor probe build_medium_batch uses
            heights, names = self._donor_context(mb, ub)
            classes = _d1c_batch.class_specs()
            class_donor = {int(c['character_id']): (c['template'], c['template_name'], c['name'])
                           for c in classes}
            donor_doc = mb.donor_for(row, heights, names, class_donor)
        storage = (int(lease['help_id']), int(lease['quest_id']), int(lease['quest_slot']))
        self._cache['sprite_shape'] = self._receiver_shape(
            entry['mod_folder'], int(lease['physical']), log)
        built = ub.build_unique(row, int(lease['identity']), int(lease['physical']), table_row,
                             table_sha, skill_doc, donor_doc, work, storage)
        _fix_help_line3(built['result']['mod'], listing)
        body = int(row['body'])
        palette, palettes = self._palette_of(listing)
        notes = [f"donor {donor_doc['donor']} ({donor_doc['donor_name']})"]
        shared = built['spec'].get('shared_rows') or []
        if shared:
            # The body carries stand/walk only; these rows are the source's own shared motion bank
            # rendered with this body's art (d5lib.d1cart.SHARED_ACTION_TAGS), not invented frames.
            rows = sorted({(s['row'], s['tags']['front'], s['tags']['back']) for s in shared})
            notes.append('source body carries stand/walk only: ' + ', '.join(
                f'{row} from source shared bank {front}/{back}' for row, front, back in rows))
        return (Path(built['result']['mod']),
                dict(kind='unique', identity=int(lease['identity']),
                     physical=int(lease['physical']), body=body, character_id=listing,
                     palette=palette, palettes=palettes,
                     skills=bool(skill_doc['skills']), notes=notes))

    def _donor_context(self, mb, ub):
        """Heights/names used by the measured donor probe, read from the *build's* own filesystem.

        ``build_entry`` copies the donor's banks out of the pristine archive (``Originals``); the
        installer's layered resolver would also see every installed mod's own art, and a family that
        exists only inside another pack (D4_Class_2050 ships anm02260, a D5 number the vanilla
        archive does not have) then wins the height probe and the build fails with
        ``KeyError: 'anm02260.lzs'`` -- Vyers 2540, 2026-11-03.  Measured on the same pristine
        resolver the build uses, that family stays 0 and is not a candidate.
        """
        from d5lib import gamefs
        from d5lib.d4unique import Originals
        pd = _d1c_batch
        fs = gamefs.GameFS(str(ub.GAME), backup_resolver=Originals(ub.STATE))
        try:
            names = dict(_d1c_batch.d5_names())
            heights = _d1c_batch.donor_heights()
            for family in pd.MONSTER_DONORS + pd.HUMANOID_DONORS:
                if not heights.get(family):
                    try:
                        heights[family] = pd.donor_stand_height(fs, family)
                    except (KeyError, ValueError, OSError):
                        heights[family] = 0
        finally:
            fs.reset()
        return heights, names

    def _receiver_shape(self, mod_folder, physical, log=None):
        """(atlas pages, palettes) of the sprite bank this unique replaces, or None.

        SOURCEPREP4-D1C: the counts come from ``d1c-bank-shapes.json`` (recorded from the installed packs);
        an installed pack is read only with ``--installed-reference``.

        The wheel-freeze rule is equality with the installed bank, and the installed D1C unique
        banks are not all the same shape: 48 of the 82 installed unique sprite banks carry 10
        palettes (the shape a fresh build produces), while 34 carry 20 because the PALFIX/PALMERGE
        graft passes appended a second 10-palette group (offset 10) and one more atlas page.  A
        rebuild must keep whatever the bank it replaces had, so the builder is told the target
        shape before it composes the atlas; see ``d5lib.ownanim.build(shape=...)``.

        A pack with no installed copy (a new entry) has no receiver shape and builds naturally.
        """
        from d5lib import anm as _anm
        installed = self._reference_pack(mod_folder)
        recorded = self._recorded(mod_folder).get('banks') or {}
        shapes = {}
        for offset in (0, 1):
            name = f'anm{physical + offset:05d}.lzs'
            if installed is None:
                if name in recorded:                       # the recorded counts of that bank (no pack is read)
                    shapes[offset] = tuple(recorded[name])
                continue
            path = installed / BANK_DIR / name
            if not path.is_file():
                continue
            try:
                a = _anm.load(path)
            except Exception:                              # noqa: BLE001 - not a sprite bank
                continue
            shapes[offset] = (len(a.textures), len(a.palettes))
        if not shapes:
            return None
        shape = shapes.get(0) or shapes.get(1)
        if len(set(shapes.values())) > 1 and log:
            log(f'  {mod_folder}: companion bank shape differs {shapes}; building on '
                f'anm{physical:05d}\'s {shape}')
        return shape

    def _palette_of(self, listing):
        """The character table's palette byte for this listing's row (D1CCUTIN1 rule input)."""
        chars = d1c_art.source().characters()
        row = next((c for c in chars if int(c['id']) == int(listing)), None)
        if row is None:
            return 0, 1
        palettes = d1c_art.source().pack()
        block = next((b for b in palettes.blocks if b.id == int(row['body'])), None)
        return int(row.get('palette') or 0), (len(block.palette_infos) if block else 1)

    # ------------------------------------------------------------------ the fix passes
    def _motion_banks(self, mod_folder):
        """The banks that carry this character's own animation pages (stand/walk/hurt slots).

        A built D1C pack has one animation bank per sprite row (``anm0<physical>.lzs``) plus a
        one-animation identity bank and the cut-in/portrait banks; only the former carry the page
        set (1001 front / 1007 back), which is what HURTSLOT1's reaction pages and the hurt gate
        are about.
        """
        from d5lib import holdblank
        return holdblank.motion_banks(mod_folder)

    def _hold_blank_keys(self, mod_folder, log, info=None):
        """BLANKKEYS1's held pose on the motion banks (REPROFIX2; shared pass since REPROFIX3).

        The rule and the reference-file fallback live in ``d5lib/holdblank.py``.  The installed pack
        of the same name decides which animation ids are held; a machine without that pack holds the
        ids recorded in ``held-blank-keys.json`` instead (REPROFIX3 (e)).  Labelled APPROXIMATION:
        the pose is held, not animated (BLANKKEYS1 sec. 3 item 3).

        -> {bank file: {animation id: keys filled}}; ``info['source']`` says 'installed'/'reference'."""
        from d5lib import holdblank
        return holdblank.hold_pack(
            mod_folder, self._reference_pack(mod_folder),
            holdblank.reference_ids('d1c', mod_folder), log=log, info=info)

    def _hurt_slots(self, mod_folder, log):
        """HURTSLOT1: the 21/27 drawing on the three reaction pages, 106 and 126."""
        sys.path.insert(0, str(self.kit / 'tools'))
        import hurtslot1_build as hs
        done = []
        for bank, ids in self._motion_banks(mod_folder):
            if not {21, 27} <= ids:                        # no source hurt art: nothing to remap
                continue
            raw = bank.read_bytes()
            try:
                out = hs.transform(bank, keep=False)
            except Exception as exc:                       # noqa: BLE001 - reported per bank
                log(f'  hurt slots skipped on {bank.name}: {type(exc).__name__}: {exc}')
                continue
            if out != raw:
                bank.write_bytes(out)
                done.append(bank.name)
        return done

    # ------------------------------------------------------------------ gates
    def _gates(self, mod_folder, entry, meta, art, hurt, block):
        from d5lib import anm
        gates = {}
        mod_json = mod_folder / 'mod.json'
        gates['mod_json'] = mod_json.is_file() and bool(json.loads(mod_json.read_text()).get('source_import'))
        banks = sorted((mod_folder / BANK_DIR).glob('anm*.lzs'))
        sprite_banks = [b for b in banks if int(b.name[3:8]) < 10000]
        cutins = [b for b in banks if int(b.name[3:8]) >= 10000]
        gates['banks'] = bool(sprite_banks)
        motion = self._motion_banks(mod_folder)
        # Did the installed copy of this pack ever carry the hurt slot?  Measured: the two humanoids
        # and the 17 uniques do (D1CMOTION2 grafted the source reaction), the D1C monsters do not.
        # Recorded in d1c-bank-shapes.json; the installed pack itself is read only on request.
        ref = self._installed_has_hurt(mod_folder.name)
        have = bool(motion) and all({21, 27} <= ids for _, ids in motion)
        if meta.get('hurt_na') and not have:
            gates['hurt_art'] = 'n/a'                     # the donor template has no hurt slot
            gates['hurt_slots'] = 'n/a'
        elif ref is False and not have:
            gates['hurt_art'] = 'n/a'                     # never existed here: nothing to restore
            gates['hurt_slots'] = 'n/a'
        else:
            gates['hurt_art'] = bool(motion)
            for bank, ids in motion:
                gates['hurt_art'] = gates['hurt_art'] and {21, 27} <= ids
            gates['hurt_slots'] = ('n/a' if meta.get('rig') else bool(hurt)) if motion else False
        # A body with no authored picture in the source pack has nothing to author: report n/a
        # (measured: the 250 cut-in blocks of start.dat[98] hold no picture for bodies 2560/5390).
        if not d1c_art.has_cutin(block) and not art['cutin']:
            gates['authored_cutin'] = 'n/a'
        else:
            gates['authored_cutin'] = bool(art['cutin'])
        # The face/cutin gate: the pack must carry a face picture (authored when the source has one,
        # otherwise the builder's standing-sprite crop, which the features record as 'adapted').
        faces = sorted((mod_folder / 'patches/characters').glob('face_*.png'))
        gates['face'] = bool(faces)
        if faces:
            from PIL import Image
            with Image.open(faces[0]) as im:
                size = im.size
            # An authored face is written at 204x204; a pack with no authored picture keeps the
            # builder's small standing-sprite crop, which the kit scales at install (reported as
            # face='adapted' in features).
            gates['face'] = (size == (d1c_art.FACE_SIZE, d1c_art.FACE_SIZE)) if art['face'] else True
        gates['cutin'] = 'n/a' if not d1c_art.has_cutin(block) else False
        for p in cutins:
            try:
                a = anm.load(p)
            except Exception:                              # noqa: BLE001 - not a picture
                continue
            if a.textures and (a.textures[0].width, a.textures[0].height) == d1c_art.CUTIN_SIZE:
                gates['cutin'] = True
                break
        # the authored picture really is the texture now in the pack (byte-level check)
        if art['cutin']:
            import numpy as np
            from PIL import Image
            picture = d1c_art.cutin_picture(block)
            a = anm.load(mod_folder / BANK_DIR / art['cutin'][0])
            texture = a.textures[0]
            want = anm._rgba_to_argb(np.asarray(
                picture.resize((texture.width, texture.height), Image.LANCZOS))).tobytes()
            gates['authored_cutin'] = texture.data == want
        # A pack whose source has no authored picture keeps the builder's adapted face (feature
        # 'adapted'); only an authored face has to be the 204 cell (CORED1CC: the earlier re-set of
        # this gate to bool(art['face']) failed 5390/6601 for a face that was never expected).
        gates['wheel_freeze'], counts = self._wheel_freeze(mod_folder, sprite_banks + cutins)
        if meta.get('rig'):
            # D1CRIG1: every motion that has a D1C twin plays the D1C source picture at every key, on one feet line
            sys.path.insert(0, str(self.kit / 'tools'))
            import d1c_motion_audit as audit
            pack = next((p for p in audit.d1c_packs(mod_folder.parent) if p['folder'] == mod_folder.name), None)
            gates['source_motions'] = bool(pack) and audit.gate(pack)[0]
        gates['identity'] = self._identity(mod_folder, entry, meta)
        return {name: (ok if ok == 'n/a' else bool(ok)) for name, ok in gates.items()}, counts

    def _installed_has_hurt(self, mod_folder):
        """True/False: did the installed copy carry 21/27 in its motion banks (None when it had no sprite bank)?

        From the installed pack when ``--installed-reference`` names one, else the recorded flag."""
        installed = self._reference_pack(mod_folder)
        if installed is None:
            return self._recorded(mod_folder).get('hurt')
        from d5lib import anm as _anm
        for bank in sorted((installed / BANK_DIR).glob('anm*.lzs')):
            if not (bank.name[3:8].isdigit() and int(bank.name[3:8]) < 10000):
                continue
            try:
                ids = {a.id for a in _anm.load(bank).blocks[0].animations}
            except Exception:                              # noqa: BLE001 - not a sprite bank
                continue
            if {1001, 1007} <= ids:
                return {21, 27} <= ids
        return None

    def _wheel_freeze(self, mod_folder, banks):
        """The wheel-freeze rule: a rebuilt bank carries *exactly* the installed bank's images.

        A palette is one more image object in the same list the loader walks (``ntex + npal``),
        and WHEELMEM1 measured the resident set grow one-for-one with them, so the freeze
        reference is the installed bank's ``(textures, palettes)`` pair, compared for *equality*.

        The old rule failed only on an increase (``have[0] <= want[0] and have[1] <= want[1]``);
        "fewer is not a freeze risk" is why the 34 unique banks dropping 20 palettes to 10 went
        through unreported -- and D1C's unique banks *are* 20-palette banks in vanilla
        (``anm00516/517/523/524/533/534/536/537/543/544/596/597``, PALFIX1 §2).  A rebuild that
        drops images has stopped carrying a bank shape the installed pack had, and only equality
        says so.

        A rebuild that legitimately lacks the installed *hurt art* is not swallowed here: the
        ``hurt_art`` gate asks for animations 21/27 by id, so that gap is still reported on its
        own terms.  Banks the installed copy does not ship (a new entry) have no reference and
        do not gate.
        """
        installed = self._reference_pack(mod_folder.name)
        recorded = self._recorded(mod_folder.name).get('banks') or {}
        counts, ok = {}, True
        from d5lib import anm, importcore
        declared = importcore.declared_shapes(mod_folder)
        for bank in banks:
            a = anm.load(bank)
            have = (len(a.textures), len(a.palettes))
            decl = declared.get(f'Anime/ANM_HI_JP.dat/{bank.name}')
            if decl is not None:
                want = (int(decl['textures']), int(decl['palettes']))
                pages = [[t.width, t.height] for t in a.textures]
                same = have == want and (not decl.get('pages') or pages == [list(x) for x in decl['pages']])
                counts[bank.name] = dict(declared=list(want), built=have, same=same, why=decl.get('why'))
                ok = ok and same
                continue
            ref = installed / BANK_DIR / bank.name if installed is not None else None
            if ref is not None and ref.is_file():
                b = anm.load(ref)
                want = (len(b.textures), len(b.palettes))
            elif installed is None and bank.name in recorded:
                want = tuple(recorded[bank.name])
            else:
                counts[bank.name] = dict(new=True, built=have)
                continue
            same = have == want
            counts[bank.name] = dict(installed=want, built=have, same=same,
                                     delta=[have[0] - want[0], have[1] - want[1]])
            ok = ok and same
        return ok, counts

    def _identity(self, mod_folder, entry, meta):
        patch = mod_folder / 'patches/db/char.dat.json'
        if not patch.is_file():
            return False
        doc = json.loads(patch.read_text())
        rows = doc.get('added') or []
        if meta['kind'] == 'unique':
            return any(int(r.get('id', -1)) == int(meta['identity']) for r in rows) or \
                   any(int(e.get('id', -1)) == int(meta['identity']) for e in (doc.get('rows') or []))
        return bool(rows or doc.get('rows'))

    # ------------------------------------------------------------------ compare
    # Files the installed D1C uniques carry from the D1CSPECIALS candidate pass (adapted D5 moves
    # under D1 names).  Specials are backlog by DECISIONS 2026-11-03: this importer builds a
    # character's own art/stats/skills, not that pass, so losing those two files is a named backlog
    # gap, not a lost character.
    SPECIALS_FILES = {'patches/db/magic.dat.json', 'patches/skills/skills.json'}

    def compare(self, entry, diff):
        """Per-entry verdict against the installed kit (interface: ``--compare-installed``)."""
        added, missing, changed = diff
        hard_missing = [m for m in missing if m not in self.SPECIALS_FILES]
        reasons = []
        if [m for m in missing if m in self.SPECIALS_FILES]:
            reasons.append('specials backlog: the installed copy carries D1CSPECIALS\' adapted '
                           'magic.dat/skills rows (DECISIONS 2026-11-03), which this command does not build')
        if hard_missing:
            return 'regression', 'rebuild lacks: ' + ', '.join(hard_missing[:6])
        art = [c for c in changed if c.startswith('files/')]
        if art:
            reasons.append(f'{len(art)} sprite bank(s) rebuilt from source: fresh atlas, source 21/27 '
                           'hurt art + HURTSLOT1 reaction pages, palettes/headers checked by wheel_freeze')
        faces = [c for c in changed + added if c.startswith('patches/characters/face_')]
        if faces:
            reasons.append('face: Disgaea 1 Complete\'s HD face (SUBDATA.DAT anmdat.fad swf####, the game\'s '
                           'sprite+palette key, D1CHDFACE1) or, with --d1c-faces installed/opaque/cutout, '
                           'the installed picture or the start.dat[73] set')
        db = [c for c in changed if c.startswith('patches/db/')]
        if db:
            reasons.append(f'{len(db)} db patch(es) re-serialised against the current tables '
                           '(same rows; personality/help ids are allocated, check `identity`)')
        other = [c for c in changed if not (c.startswith('files/') or c.startswith('patches/db/')
                                            or c.startswith('patches/characters/face_'))]
        if other:
            reasons.append('other files differ: ' + ', '.join(other[:3]))
        if added:
            reasons.append('adds ' + ', '.join(added[:3]))
        return ('expected', '; '.join(reasons)) if reasons else ('identical', '')

    # ------------------------------------------------------------------ pack level
    def post(self, out_dir, results):
        """Write the pack manifest and the D1C catalogue entry list for the runner."""
        out_dir = Path(out_dir)

        def row(r):
            if isinstance(r, dict):
                return r
            return dict(id=r.id, mod_folder=r.mod_folder, built=r.built,
                        features=r.features, art=(r.extra or {}).get('art', {}))

        results = [row(r) for r in results]
        built = [r for r in results if r.get('built')]
        doc = dict(schema=1, game='d1c', source='Disgaea 1 Complete (Switch, D1CSRC1)',
                   entries=[dict(id=r['id'], mod=r['mod_folder'], features=r.get('features', {}),
                                 art=r.get('art', {})) for r in built],
                   counts=dict(entries=len(results), built=len(built),
                               authored_face=sum(1 for r in built if r.get('features', {}).get('face') == 'own'),
                               authored_cutin=sum(1 for r in built if r.get('features', {}).get('cutin') == 'own')))
        (out_dir / 'd1c-manifest.json').write_text(json.dumps(doc, indent=2) + '\n')
        return doc
