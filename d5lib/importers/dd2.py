"""Offline DD2 rebuild plugin; baseline and reviewed abilities are separate outputs.

The frozen roster is the installed MAIN DD2_* selection. Parked D2_* pilots
are excluded. Source tables and art come from the prepared source folder (or an
explicit --source-root), never the install.  See importcore/COREDD2-REPORT.md
for the recipes and evidence boundaries, and
Subprojects/Engine-Extensions/SOURCEPREP4-DD2-REPORT.md for the input map.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..importcore import Result


def original_fs(ctx):
    """Use the canonical backup index without constructing a writable Installer.

    Installer.__init__ creates state directories. Offline import only needs its
    read-only resolver, so bind that method to an object with the existing index.
    """
    from .. import gamefs, modsys
    state = Path(ctx['state_root'])
    resolver = object.__new__(modsys.Installer)
    resolver.index = json.loads((state / 'backups.json').read_text())
    resolver.backup_dir = str(state / 'backups')
    return gamefs.GameFS(str(ctx['game_path']), backup_resolver=resolver.backup_resolver)


def validate_pack(pack):
    """Kit identity validator and strict ANM parse/header/round-trip checks."""
    from .. import anm, classcheck, gamefs
    findings = classcheck.check(pack, control_codes=True)
    failures = classcheck.gate(findings)
    notes = [f"{f['rule']}: {f['message']}" for f in failures]
    parsed_count = 0
    for path in sorted((Path(pack) / 'files').rglob('anm*.lzs')):
        try:
            raw = gamefs.decode_member(path.read_bytes())
            parsed = anm.parse(raw)
            for image in parsed.textures + parsed.palettes:
                if image.unk != 1:
                    raise ValueError(f'image byte-order marker {image.unk:#x}, expected 1')
                if len(image.data) != image.expected_size():
                    raise ValueError('truncated image data')
            if parsed.to_bytes(fix_virtual_offsets=False) != raw:
                raise ValueError('ANM serialization does not round-trip')
            parsed_count += 1
        except Exception as exc:
            notes.append(f'{path.name}: {type(exc).__name__}: {exc}')
    anm_errors = len(notes) > len(failures)
    return {'identity': not failures, 'anm': parsed_count > 0 and not anm_errors}, notes


class Importer:
    game = 'dd2'

    def _hold_blank_keys(self, entry, pack, ctx):
        """REPROFIX3: BLANKKEYS1's held pose on the motion banks, as a build pass.

        The installed pack of the same name decides which animation ids are held; with no installed
        pack the ids recorded in ``held-blank-keys.json`` are held instead (REPROFIX3 (e)).  The rule
        is shared with the D1C/D4 importers (``d5lib/holdblank.py``); labelled APPROXIMATION.
        -> (held, source)"""
        from d5lib import holdblank
        # SOURCEPREP4-DD2: the default build holds the recorded ids; the installed bank is only
        # read when a comparison is explicitly requested, so a fresh machine needs no install.
        installed = None
        if ctx.get('installed_reference', True) and ctx.get('installed_root'):
            candidate = Path(ctx['installed_root']) / entry.mod_folder
            installed = candidate if candidate.is_dir() else None
        info = {}
        held = holdblank.hold_pack(
            pack, installed,
            holdblank.reference_ids('dd2', entry.mod_folder), log=lambda _s: None, info=info)
        return held, info.get('source')

    @staticmethod
    def _hold_note(held, source):
        if not held:
            return None
        return ('blank key times held (BLANKKEYS1 rule, labelled approximation, '
                + ('installed reference' if source == 'installed'
                   else 'held-blank-keys.json: no installed pack')
                + '): ' + ', '.join(f'{b} {sorted(ids)}' for b, ids in held.items()))

    def roster(self, source_root=None):
        from ._dd2_baseline import roster
        return roster(source_root)

    def wheel_reference(self, folder):
        """The recorded ANM shape table used when no installed pack is read (SOURCEPREP4-DD2)."""
        from ._dd2_source import wheel_reference
        return wheel_reference(folder)

    def build(self, entry, out_dir, ctx):
        from ._dd2_baseline import build_baseline
        out_dir = Path(out_dir)
        pack, receipt = build_baseline(entry, out_dir, ctx)
        pack = Path(pack)
        result = Result(id=entry.id, mod_folder=entry.mod_folder, built=True)
        result.notes = list(receipt.get('notes', []))
        result.features = dict(receipt.get('features', {}))
        reviewed = os.environ.get('D5_DD2_REVIEWED_ABILITIES') == '1'
        if reviewed:
            from ._dd2_abilities import apply_reviewed
            ability_ctx = dict(ctx)
            fs = original_fs(ctx)
            try:
                ability_ctx['fs'] = fs
                additions = apply_reviewed(pack, entry, ability_ctx)
            finally:
                fs.reset()
            receipt['reviewed_abilities'] = additions
            result.features.update(additions.get('features', {}))
            result.notes.append('reviewed abilities emitted; see reviewed-abilities.json')
            (out_dir / 'reviewed-abilities.json').write_text(
                json.dumps(additions, indent=2, ensure_ascii=False) + '\n')
        if (ctx.get('options') or {}).get('dd2_hold_blank', True):
            # REPROFIX3: BLANKKEYS1's held pose (Pringer Z anm00676, Baal Slave anm00683)
            try:
                held, hsource = self._hold_blank_keys(entry, pack, ctx)
                if held:
                    result.extra['hold_blank'] = held
                    result.extra['hold_blank_source'] = hsource
                    result.notes.append(self._hold_note(held, hsource))
            except Exception as exc:                   # noqa: BLE001 - reported
                result.notes.append(f'hold blank keys: {type(exc).__name__}: {exc}')
        from . import _dd2_innates                     # EVILFX3: the innate evility a pack linked none of
        note = _dd2_innates.apply(pack, entry.mod_folder)
        if note:
            result.notes.append(note)
            result.gates['innate_evility'] = _dd2_innates.gate(pack, entry.mod_folder)[0]
        # after the reviewed layer: the installed copy carries it (COREDD2-ABILITIES.json, mod.json key)
        from ._dd2_baseline import leases
        if leases()[entry.mod_folder].get('new'):
            # ROSTERGAP1: a lease marked new has no installed copy, so there is no baseline to preserve
            result.notes.append('new entry: no installed baseline, baseline_preserved not applicable')
        elif not ctx.get('installed_reference', True) or not ctx.get('installed_root'):
            # SOURCEPREP4-DD2: the default build does not read the install at all; the comparison
            # is an explicit, read-only opt-in (--compare-installed).
            result.notes.append('installed comparison not requested: baseline_preserved not checked')
        elif not (Path(ctx['installed_root']) / entry.mod_folder).is_dir():
            result.notes.append('no installed copy of this pack: baseline_preserved not checked')
        else:
            from ._dd2_validation import baseline_preserved
            baseline_ok, differences = baseline_preserved(
                pack, Path(ctx['installed_root']) / entry.mod_folder, strict=False)
            result.gates['baseline_preserved'] = baseline_ok
            result.notes.extend(differences)
        if (ctx.get('options') or {}).get('dd2_source_fields', True):
            # DD2FIELDS1: every carried battle field of the built row must equal the source row, and a unique's
            # default palette must be a source palette (d5lib/dd2fieldaudit.py; the old donor-inheriting path fails it)
            from .. import dd2fieldaudit
            from ._dd2_baseline import source_data
            try:
                rows = dd2fieldaudit.load_rows(source_data(ctx.get('source_root')).path('START_4.dat'))
            except Exception as exc:                   # noqa: BLE001 - a build without readable source has no baseline either
                result.notes.append(f'source_fields not checked: {type(exc).__name__}')
            else:
                field_audit = dd2fieldaudit.audit_pack(pack, rows)
                pal = field_audit['palette'] or {}
                result.gates['source_fields'] = (not field_audit['mismatches']
                                                 and (not pal.get('checked') or pal['fraction'] >= 1.0))
                result.notes.extend(f"source_fields: rank {m['rank']} {m['field']} source {m['source']} built {m['built']}"
                                    for m in field_audit['mismatches'][:20])
        if (ctx.get('options') or {}).get('dd2_cutin_fit', True):
            # DD2CUTIN1: every cut-in bank is one uniform scale of the source cut-in, loses no pixel, and a class
            # rank holds its own strip (d5lib/dd2cutinaudit.py; the old stretching path fails it)
            from .. import dd2cutinaudit
            from ._dd2_baseline import source_data
            try:
                meta = json.loads((pack / 'mod.json').read_text())
                cutin_audit = dd2cutinaudit.audit_pack(pack, dd2cutinaudit.source_images(meta, source_data(ctx.get('source_root'))))
            except Exception as exc:                   # noqa: BLE001 - a build without readable source has no baseline either
                result.notes.append(f'cutin_fit not checked: {type(exc).__name__}: {exc}')
            else:
                result.gates['cutin_fit'] = not cutin_audit['failed']
                receipt['cutin_fit'] = cutin_audit      # measured placement of every cut-in bank (scale, box, difference)
                result.notes.extend(f"cutin_fit: {line}" for line in cutin_audit['failed'][:20])
        gates, notes = validate_pack(pack)
        result.gates.update(gates)
        result.notes.extend(notes)
        (out_dir / 'coredd2-receipt.json').write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False) + '\n')
        return result

    def post(self, mods_root, results):
        root = Path(mods_root).parent
        receipts = {}
        for path in sorted((root / 'build').glob('*/reviewed-abilities.json')):
            receipts[path.parent.name] = json.loads(path.read_text())
        if receipts:
            (root / 'reviewed-abilities.json').write_text(
                json.dumps(receipts, indent=2, ensure_ascii=False) + '\n')

    def compare_reason(self, entry, diff):
        from ._dd2_baseline import compare_reason
        return compare_reason(entry, diff)
