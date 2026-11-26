"""BLANKKEYS1's held pose as a build pass, shared by the D1C, D4 and DD2 importers (REPROFIX2/REPROFIX3).

A whole-body import keeps ONE body track per animation; where the donor's body moves on a track the
import hides, the imported pose is blank at some key times and the animation flickers to nothing.
BLANKKEYS1 measured that on the *installed* packs and patched some of them with
``ownanim.hold_blank_keys`` (the nearest earlier drawn key of the same private layer is repeated;
shared layers and animations that draw nothing are left alone).

The importer pass (REPROFIX2 for D1C, REPROFIX3 for D4 and DD2) decides which animations are held
from the **installed pack of the same name**, never from a blanket rule: BLANKKEYS1 held some blanks
and not others (Lantern 1501/1507 keeps its trailing blank).  An animation is held when the installed
bank of the same file has the same key times and draws on a proper superset of the rebuilt one's key
times -- i.e. the install fills blanks the build leaves.

A machine with no installed pack has no reference.  For that case ``held-blank-keys.json`` beside the
importers records the bank file names and animation ids the installed-reference pass holds (ids only,
no game data); the pass then holds those ids.  The result is the same set of held animations as a
build against the install; the pose is the same approximation either way (BLANKKEYS1 sec. 3 item 3:
held, not animated).  A pack absent from the file is left alone, exactly as with no installed
reference.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import anm, lzs, ownanim

BANK_DIR = Path('files/Anime/ANM_HI_JP.dat')
PAGE_IDS = frozenset({1001, 1007})            # front / back sprite pages a motion bank carries
REFERENCE_FILE = Path(__file__).resolve().parent / 'importers' / 'held-blank-keys.json'


def motion_banks(mod_folder, bank_dir=BANK_DIR, pages=PAGE_IDS):
    """The banks that carry this character's own animation pages (stand/walk/hurt slots).

    A built pack has one animation bank per sprite row (``anm0<physical>.lzs``) plus a
    one-animation identity bank and the cut-in/portrait banks; only the former carry the page
    set, which is what the held pose is about.  -> [(Path, {animation ids})]
    """
    out = []
    for bank in sorted((Path(mod_folder) / bank_dir).glob('anm*.lzs')):
        if not (bank.name[3:8].isdigit() and int(bank.name[3:8]) < 10000):
            continue                                   # cut-in / portrait anms, not sprite banks
        try:
            ids = {a.id for a in anm.load(bank).blocks[0].animations}
        except Exception:                              # noqa: BLE001 - not a sprite bank
            continue
        if pages <= ids:
            out.append((bank, ids))
    return out


def drawn_times(fl, aid):
    """(key times, the subset of them where the animation draws anything at all)"""
    ts = anm.frame_times(fl, ('id', aid))
    return ts, {t for t in ts
                if any(i.cell.w > 0 and i.cell.h > 0
                       for i in anm.evaluate(fl, ('id', aid), t, nested=True))}


def hold_ids_from_installed(build_anm, installed_anm):
    """Animation ids to hold: the install draws on a proper superset of the build's drawn key times.

    The same clock is required; the inverse (the build drawing more) is a newer source animation,
    not something a held pose may touch."""
    try:
        inst_ids = {a.id for _, _, a in installed_anm.all_animations()}
    except Exception:                                  # noqa: BLE001
        return []
    out = []
    for _bi, _ai, anim in build_anm.all_animations():
        if anim.id not in inst_ids:
            continue
        its, inst_drawn = drawn_times(installed_anm, anim.id)
        mts, mine_drawn = drawn_times(build_anm, anim.id)
        if its != mts or not (mine_drawn < inst_drawn):
            continue
        out.append(anim.id)
    return out


def hold_pack(mod_folder, installed_mod=None, reference_ids=None, log=print,
              bank_dir=BANK_DIR, pages=PAGE_IDS, info=None):
    """Hold the blank key times on every motion bank of ``mod_folder``.

    ``installed_mod``: the installed pack to read the reference bank from (None = none).  When it is
    None or a bank of that name is not there, ``reference_ids`` ({bank file name: [animation id]},
    the held-blank-keys.json entry) is used instead.  ``info`` (a dict) receives ``source``:
    ``'installed'``, ``'reference'`` or None.  -> {bank file name: {animation id: keys filled}}"""
    mod_folder = Path(mod_folder)
    installed_dir = (Path(installed_mod) / bank_dir) if installed_mod else None
    reference_ids = reference_ids or {}
    done = {}
    source = None
    for bank, _ids in motion_banks(mod_folder, bank_dir, pages):
        ref = (installed_dir / bank.name) if installed_dir else None
        a = anm.load(bank)
        held = {}
        compared = False                               # an installed bank was read: it alone decides
        if ref is not None and ref.is_file():
            try:
                installed = anm.load(ref)
            except Exception:                          # noqa: BLE001 - not a bank, hold from the file if listed
                installed = None
            if installed is not None:
                compared = True
                for aid in hold_ids_from_installed(a, installed):
                    n = ownanim.hold_blank_keys(a, aid)
                    if n:
                        held[aid] = n
                if held:
                    source = source or 'installed'
        if not held and reference_ids and not compared:
            for aid in sorted(set(reference_ids.get(bank.name) or ())):
                if any(x.id == aid for _, _, x in a.all_animations()):
                    n = ownanim.hold_blank_keys(a, aid)
                    if n:
                        held[aid] = n
            if held:
                source = source or 'reference'
        if not held:
            continue
        raw = bank.read_bytes()
        out = a.to_bytes()
        if raw[:4] in (b'dat\0', b'pac\0'):            # keep the member's storage form
            out = anm.lzs_compress(out, lzs.header_ext(raw))
        bank.write_bytes(out)
        done[bank.name] = held
        log(f"  hold blank keys ({source}): {bank.name} {held}")
    if info is not None:
        info['source'] = source
    return done


_REFERENCE = None


def reference_doc():
    """The held-ids data file (cached): {'games': {game: {pack: {bank: [ids]}}}, ...}."""
    global _REFERENCE
    if _REFERENCE is None:
        _REFERENCE = (json.loads(REFERENCE_FILE.read_text(encoding='utf-8'))
                      if REFERENCE_FILE.is_file() else {'games': {}})
    return _REFERENCE


def reference_ids(game, mod_folder):
    """The held ids recorded for this pack, or None when the pack is not in the file."""
    return (reference_doc().get('games', {}).get(game, {}).get(Path(mod_folder).name))
