"""Offline DRPG base-family importer; wraps the Kit sample and outfit builders.

SOURCEPREP4-DRPG: every game input comes through the prepared source folder (``_drpg_source.DrpgData``: verified
manifest rows only).  The reviewed roster is ``drpg-roster.json`` (ids, rules and text references, no game text);
the original JP cache stays in its Android image: this plugin does not boot or extract it, the user supplies
unpacked files.  Every consumed PNG is pinned separately (path label, SHA-256 of the verified row).
"""
from __future__ import annotations
import copy
import json
import subprocess
import sys
import threading
from pathlib import Path
from ..importcore import Entry, Result
from . import _drpg_roster, _drpg_source

KIT = Path(__file__).resolve().parents[2]
SLICE = (94, 55, 106, 20009, 337)
# Incoming offline lanes have published these leases in their reports but have
# not installed them into MAIN yet. Keep their art windows free at integration.
PENDING_ART_LEASES = {643: "CORED4C Pringer X", 646: "CORED1CC Fl:F.Angel",
                      653: "CORED1CC Carter"}
NAMES = {55: 'DRPG_Sample_Noel', 106: 'DRPG_Sample_Melodia', 311: 'DRPG_Sample_Citri'}
_LOCK = threading.Lock()


def family_kind(looks):
    kinds = {x['type'] for x in looks}
    return ('humanoid-with-monster-variant' if kinds == {'humanoid', 'monster'} else
            'monster' if kinds == {'monster'} else 'humanoid')


def reviewed_characters(snapshot, decision_doc):
    """Apply the identity decisions, rebuilding mappings for changed membership.

    The decision manifest is authoritative for scope and look ownership. Source
    mappings remain unchanged only when their assigned look set is unchanged.
    """
    if decision_doc.get('schema') != 'drpg-grouping-decisions/1':
        raise ValueError('Unsupported DRPG grouping-decisions schema')
    from ._drpg_zed import mapped_family
    prior = {c['base_id']: c for c in snapshot}
    seen_bases = set(); seen_looks = set(); out = []
    for group in decision_doc['characters']:
        bid = group['base_id']; looks = group['looks']
        ids = [l['id'] for l in looks]
        if bid in seen_bases or not looks or len(set(ids)) != len(ids) or seen_looks.intersection(ids):
            raise ValueError(f'Duplicate base/look assignment or empty DRPG group {bid}')
        best = group['best_base_look_id']
        if best not in ids:
            raise ValueError(f'DRPG group {bid} best look {best} is not assigned to it')
        seen_bases.add(bid); seen_looks.update(ids)
        old = prior.get(bid)
        if old and {l['id'] for l in old['looks']} == set(ids):
            character = copy.deepcopy(old)
        else:
            variants = [dict(id=l['id'], english_name=l.get('en'), japanese_name=l.get('jp'),
                             type=l['type'], art=l.get('art', {}),
                             catalog_outfits=l.get('outfits', [])) for l in looks]
            character = mapped_family(dict(base_id=bid, base_name=group['name'],
                                            variants=variants, source_game=group.get('origin_game')))
        character.update(base_id=bid, name=group['name'], looks=copy.deepcopy(looks),
                         distinct_looks=len(looks), kind=family_kind(looks),
                         outfits_plan=[dict(look_id=l['id'], name=l.get('en') or l.get('jp'),
                                            type=l['type']) for l in looks if l['id'] != best])
        out.append((character, best))
    return out


def entries(characters, roster_sha):
    """Roster entries from resolved ``[(character record, best look id)]`` (``_drpg_roster.characters``)."""
    out = []
    for c, best in characters:
        bid = c['base_id']
        folder = NAMES.get(bid, f"DRPG_Core_{''.join(x for x in c['name'] if x.isalnum())}_{bid}")
        ref = dict(file='drpg-roster-*.json', sha256=roster_sha, row={'base_id': bid},
                   original_root=_drpg_source.LABEL, art_policy='original-verified-prepared-only',
                   character=c, best_base_look=best)
        out.append(Entry(f'drpg:{bid}', family_kind(c['looks']), c['name'].strip(), folder, ref))
    return sorted(out, key=lambda e: (SLICE.index(int(e.id.split(':')[1])) if int(e.id.split(':')[1]) in SLICE else 5,
                                      int(e.id.split(':')[1])))


def _owned_marker(folder):
    folder = Path(folder)
    return folder.parent / f'.{folder.name}.d5-drpg-created.json'   # beside the folder, never inside the pack


def record_created(folder):
    """List every file of a finished build folder, so the next run removes exactly those and nothing else."""
    folder = Path(folder)
    marker = _owned_marker(folder)
    files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob('*')
                   if p.is_file())
    marker.write_text(json.dumps(dict(schema='d5-drpg-created/1', files=files), indent=1) + '\n')


def remove_created(folder, strict=False):
    """Remove the files a previous build of this importer recorded in ``folder``; anything else stays.

    A folder with no record is not ours: it is refused untouched (the caller reports it)."""
    folder = Path(folder)
    if not folder.exists():
        return
    marker = _owned_marker(folder)
    if not marker.is_file():
        if not any(folder.iterdir()):
            folder.rmdir()
            return
        raise FileExistsError(f'{folder} exists and was not created by this importer (no {marker.name}); '
                              'not deleting it. Choose another --out folder.')
    doc = json.loads(marker.read_text())
    for rel in doc.get('files', []):
        target = folder / rel
        if target.is_symlink():                 # a link this importer staged (own cut-in): drop the link, never its target
            target.unlink()
        elif target.is_file() and folder.resolve() in target.resolve().parents:   # both resolved: a symlinked parent (/tmp, /var) must not hide our own files
            target.unlink()
    marker.unlink()
    if strict:
        foreign = sorted(p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file() or p.is_symlink())
        if foreign:
            raise FileExistsError(f'{folder} holds files this importer did not create ({", ".join(foreign[:3])}); '
                                  'they would be readable as source art, so the folder is not reused. Choose another --out folder.')
    for sub in sorted((p for p in folder.rglob('*') if p.is_dir()), key=lambda p: -len(p.parts)):
        try:
            sub.rmdir()
        except OSError:
            pass
    try:
        folder.rmdir()
    except OSError:
        pass


class Importer:
    game = 'drpg'

    def __init__(self):
        self._rosters = {}
        self._ctx = {}

    def configure(self, game_path=None, state_root=None):
        """The Disgaea 5 install the text references of the roster resolve against (called by importcore.run)."""
        self._ctx = dict(game_path=game_path, state_root=state_root)

    def roster(self, source_root=None):
        key = str(source_root or '')
        if key not in self._rosters:
            data = _drpg_source.data(source_root)
            fs = None
            if self._ctx.get('game_path') and self._ctx.get('state_root'):
                from ._drpg_build import source_fs
                fs = source_fs(self._ctx)
            try:
                pool = _drpg_roster.TextPool.from_sources(data, fs)
                chars = _drpg_roster.characters(pool)
            finally:
                if fs is not None:
                    fs.reset()
            self._rosters[key] = entries(chars, _drpg_roster.file_sha256())
        return list(self._rosters[key])

    def icon_pins(self, folder):
        """The list-icon pairs of the shipped pack (``drpg-bank-shapes.json``): what ``pin_installed_icons`` read from it."""
        return _drpg_roster.icon_pins(Path(folder).name)

    def wheel_reference(self, folder):
        """Recorded ANM header shapes of the shipped pack (``drpg-bank-shapes.json``), or ``{}``."""
        files = _drpg_roster.bank_shapes().get(Path(folder).name) or {}
        return {rel: tuple(shape) for rel, shape in files.items()}

    def build(self, entry, out_dir, ctx):
        # The Kit allocators and caches have process-global hooks. Each worker is
        # isolated; serialize peak archive memory and independent lease planning.
        with _LOCK:
            from ._drpg_build import plan
            output_root = Path(ctx['output_root']).resolve()
            protected = [Path(ctx[k]).resolve() for k in ('game_path','installed_root','source_root') if ctx.get(k)]
            if not out_dir.resolve().is_relative_to(output_root) or any(
                    output_root.is_relative_to(p) or p.is_relative_to(output_root) for p in protected):
                return Result(entry.id,entry.mod_folder,error='Unsafe output: DRPG builds must be separate from original source, game and installed mods')
            out_dir.mkdir(parents=True, exist_ok=True)
            # Re-running the command must not append old costumes or accept a
            # previous receipt after a failed worker. Only this entry is reset.
            (out_dir/'receipt.json').unlink(missing_ok=True)
            previous = out_dir/'native-mods'/entry.mod_folder
            try: remove_created(previous)
            except FileExistsError as exc:
                return Result(entry.id, entry.mod_folder, error=str(exc))

            from . import drpg_leases
            try:
                leases = drpg_leases.load()
                problems = drpg_leases.verify(leases)
            except (OSError, ValueError) as exc:
                leases, problems = None, [f"unreadable: {exc}"]
            if problems:
                # fail closed: the old pool allocator set sprite = row, which K0 measured as 44 lost base leases
                return Result(entry.id, entry.mod_folder,
                              error="DRPG v2 lease manifest is invalid (d5lib/importers/drpg-leases.json): "
                                    + "; ".join(problems))
            allocation = plan(self.roster(ctx.get('source_root')), ctx, leases=leases)
            payload = dict(entry=entry.__dict__, ctx={k:str(v) if isinstance(v, Path) else v for k,v in ctx.items()},
                           allocation=allocation.get(entry.id))
            if not payload['allocation']:
                return Result(entry.id, entry.mod_folder, error='Current DRPG allocator has no collision-free low unique/outfit lease for this group; consult importcore/CORERPG2-REPORT.md before broad builds')
            request = out_dir / 'request.json'; request.write_text(json.dumps(payload, ensure_ascii=False))
            logfile = out_dir / 'build.log'
            with logfile.open('w') as log:
                p = subprocess.run([sys.executable, '-B', '-m', 'd5lib.importers._drpg_build', str(request)],
                                   cwd=KIT, stdout=log, stderr=subprocess.STDOUT)
            if (out_dir/'native-mods'/entry.mod_folder).is_dir(): record_created(out_dir/'native-mods'/entry.mod_folder)
            receipt_path = out_dir / 'receipt.json'
            if not receipt_path.exists():
                tail = logfile.read_text()[-1500:]
                return Result(entry.id, entry.mod_folder, error=f'worker rc={p.returncode}: {tail}', log=str(logfile))
            receipt = json.loads(receipt_path.read_text())
            r = Result(entry.id, entry.mod_folder, built=receipt['ok'], gates=receipt['gates'],
                       features=receipt['features'], notes=receipt['notes'], log=str(logfile))
            if p.returncode or not receipt['ok']:
                r.error = receipt.get('error') or f'worker rc={p.returncode}'
            return r
