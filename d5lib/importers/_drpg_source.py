"""Every game input of the Disgaea RPG importer, and where it comes from (SOURCEPREP4-DRPG).

The importer reads the user's own *unpacked* Disgaea RPG (JP) files, and only through the prepared source folder
(SOURCEPREP2, ``d5lib/sourcefolder.py``, ``tools/prep_source.py --drpg ...``).  :class:`DrpgData` is the only way a
DRPG reader gets a byte of that data:

* a file is readable only when the folder's ``manifest.json`` lists it for ``drpg`` with ``verified: "yes"``, it is on
  disk, its size equals the row's and its SHA-256 equals the row's.  The hash is taken from the very bytes handed to
  the caller (one read), so a same-size replacement of a verified file is refused, not trusted;
* a file that merely sits in the folder (an extra PNG, a ``.bak`` copy, a second voice bank) is never returned by any
  route, optional ones included: sprites, icons, cut-ins, voice banks and masters are all asked for by the exact
  relative path the manifest owns;
* nothing here opens ``Disgaea Source``, a Forge art folder, a Builds folder or an installed pack.

The users supply unpacked files (no UnityPy here).  Disgaea RPG JP is the source; the Global client is not used.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .. import sourcefolder

GAME = 'drpg'
LABEL = 'drpg'
SPRITES = 'sprites'
DECODE_BUILD = 'drpg-jp-client-decoded'      # known-table build of the optional rows (hashes of the separate client decode)
VOICE_BANKS = 'assetbundle/sounds/voice/battle'
# The sheet roles the importer needs (RPGEXTRACT1 layout under ``sprites/``) and the optional ones.
SHEETS = (('front', 'Sprites/Standard/BattleFront', 'front'), ('back', 'Sprites/Standard/BattleBack', 'back'),
          ('wait_front', 'Sprites/Standard/WaitFront', 'front'), ('wait_back', 'Sprites/Standard/WaitBack', 'back'))
REQUIRED_ROLES = tuple(role for role, _sub, _stem in SHEETS)
HINT = 'Run `python tools/prep_source.py --drpg <your unpacked DRPG folder>` (or point D5_SOURCE_DIR at a prepared folder).'


class DrpgSourceError(RuntimeError):
    """A DRPG input is missing, unverified or changed; the message names ``drpg/<file>`` and how to supply it."""


def unit_files(uid):
    """{role: path relative to the drpg folder} of one unit's recognised files (listed or not)."""
    uid = int(uid)
    out = {role: f'{SPRITES}/{sub}/{stem}{uid}.png' for role, sub, stem in SHEETS}
    out['icon'] = f'{SPRITES}/Chara Icons/{uid}.png'
    out['cutin'] = f'{SPRITES}/Cutins/{uid}.png'
    return out


def voice_files(look):
    look = int(look)
    return {part: f'{VOICE_BANKS}/{look}/{look}_{part}' for part in ('acb', 'awb')}


class DrpgData:
    """The verified Disgaea RPG input set of one prepared source folder."""

    def __init__(self, folder, rows):
        self.folder = Path(folder)
        self._rows = dict(rows)

    # ------------------------------------------------------------------------------------ state of one file
    def status(self, rel):
        """'ok' | 'unlisted' | 'unverified' | 'missing' | 'resized' | 'nodigest' for the manifest row of ``rel``."""
        row = self._rows.get(rel)
        if row is None:
            return 'unlisted'
        if row.get('verified') != 'yes':
            return 'unverified'
        path = self.folder / GAME / rel
        if not path.is_file():
            return 'missing'
        if row.get('size') is not None and path.stat().st_size != int(row['size']):
            return 'resized'
        if not row.get('sha256'):
            return 'nodigest'
        return 'ok'

    def have(self, rel):
        return self.status(rel) == 'ok'

    def _refuse(self, rel, state):
        row = self._rows.get(rel) or {}
        why = {
            'unlisted': f'no manifest row ({HINT})',
            'unverified': f"manifest says verified {row.get('verified')!r} (size/SHA-256 do not match a known "
                          'Disgaea RPG JP client)',
            'missing': f'listed as verified but the file is missing from {self.folder / GAME}',
            'resized': f'size differs from the manifest ({row.get("size")}); re-run tools/prep_source.py --drpg ...',
            'nodigest': 'the manifest row carries no SHA-256, so the file cannot be trusted (re-run tools/prep_source.py)',
        }[state]
        raise DrpgSourceError(f'{LABEL}/{rel}: {why}')

    def read(self, rel):
        """The bytes of one verified file; refuses a missing row, an unverified row and any changed bytes."""
        state = self.status(rel)
        if state != 'ok':
            self._refuse(rel, state)
        raw = (self.folder / GAME / rel).read_bytes()
        got = hashlib.sha256(raw).hexdigest()
        if got != self._rows[rel]['sha256']:
            raise DrpgSourceError(f'{LABEL}/{rel}: the bytes on disk (SHA-256 {got[:16]}...) no longer match the '
                                  f'verified manifest row ({self._rows[rel]["sha256"][:16]}...); '
                                  're-run tools/prep_source.py --drpg ...')
        return raw

    def provenance(self, rel):
        """'derived-fallback' for a row of the separate client decode (optional rows: monster twins and the 14 variant looks),
        'original' for a row of the RPGEXTRACT1 decode; the label receipts have always carried."""
        return 'derived-fallback' if str((self._rows.get(rel) or {}).get('known_build', '')).startswith(DECODE_BUILD) else 'original'

    def sha256(self, rel):
        """The manifest's SHA-256 of a verified row (proven against the bytes by :meth:`read`)."""
        state = self.status(rel)
        if state != 'ok':
            self._refuse(rel, state)
        return self._rows[rel]['sha256']

    # ------------------------------------------------------------------------------------ routes
    def unit_assets(self, uid):
        """{role: rel} for the unit's files that are verified; a role that is not owned by the manifest is absent."""
        return {role: rel for role, rel in unit_files(uid).items() if self.have(rel)}

    def sheets_complete(self, uid):
        return all(role in self.unit_assets(uid) for role in REQUIRED_ROLES)

    def voice_bank(self, look):
        """{'acb': rel, 'awb': rel} when both banks of the look are verified; raises otherwise."""
        files = voice_files(look)
        for rel in files.values():
            state = self.status(rel)
            if state != 'ok':
                self._refuse(rel, state)
        return files

    def voice_looks(self):
        """Look ids whose two voice banks are both verified."""
        out = []
        for rel in self._rows:
            if rel.startswith(VOICE_BANKS + '/') and rel.endswith('_acb'):
                look = rel.split('/')[-2]
                if look.isdigit() and self.have(rel) and self.have(voice_files(look)['awb']):
                    out.append(int(look))
        return sorted(out)

    def to_config(self):
        return dict(folder=str(self.folder))

    @classmethod
    def from_config(cls, doc):
        return data(doc['folder'])


def data(explicit=None):
    """The verified DRPG input: the prepared source folder (``explicit`` names a prepared folder, never a bare dump)."""
    folder = Path(explicit) if explicit else sourcefolder.source_dir()
    manifest = folder / sourcefolder.MANIFEST_FILE
    if not manifest.is_file():
        raise DrpgSourceError(f'No prepared DRPG source: {manifest} is missing. {HINT}')
    try:
        doc = sourcefolder.read_manifest(folder)
    except (OSError, ValueError) as exc:
        raise DrpgSourceError(f'Prepared source manifest {manifest} is unreadable: {exc}') from exc
    entry = (doc.get('games') or {}).get(GAME) or {}
    rows = {row.get('path'): row for row in entry.get('files', []) if row.get('path')}
    if not rows or entry.get('supplied') is False:
        raise DrpgSourceError(f'The prepared source folder {folder} has no Disgaea RPG files. {HINT}')
    return DrpgData(folder, rows)
