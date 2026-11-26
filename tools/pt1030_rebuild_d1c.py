"""Rebuild the ART of one D1C class pack with the converted rules, into a scratch folder.

The pack's db/text patches are never regenerated: only the three Anime/ANM_HI_JP.dat banks are
produced, so an overlay can carry them onto TEST18B without reverting later lanes' text work.

  PYTHONPATH=. D5_KIT=<worktree> python tools/pt1030_rebuild_d1c.py --batch monsters --only 11930 --work <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

KIT = Path(os.environ.get('D5_KIT') or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(KIT))

from d5lib.importers import _d1c_batch as bb          # noqa: E402  (the kit's source-packet builder; SOURCEPREP4-D1C)
from d5lib import nativeimports, sprites   # noqa: E402


def add_shared_lift(spec, packet_dir, manifest, receipt):
    """Replace the held launch input with body-bound bank 1 drawings, preserving its canvas pivot."""
    from PIL import Image
    from d5lib import d1cart
    result = d1cart.shared_lift(bb.ART, manifest['body'])
    if result is None:
        raise ValueError('Shared lift bank 1 is missing')
    lift, evidence = result
    old = receipt['canvas']['bounds']
    bounds = evidence['bounds']
    union = [min(old[0], bounds[0]), min(old[1], bounds[1]),
             max(old[2], bounds[2]), max(old[3], bounds[3])]
    canvas = [int(old[3]-old[1]), int(old[2]-old[0]),
              int(old[1]-union[1]), int(old[0]-union[0])]
    for bundle in manifest['bundles']:
        view = bundle['label']
        bundle['sprites'] = [item for item in bundle['sprites'] if not item['name'].startswith('launch')]
        for n, image in enumerate(lift[('launch', view)]):
            extended = Image.new('RGBA', (int(union[2]-union[0]), int(union[3]-union[1])))
            extended.paste(image, (int(bounds[0]-union[0]), int(bounds[1]-union[1])))
            name = f'launch{n+1:02d}'
            path = f'{view}/{name}.png'
            extended.save(packet_dir / path)
            bundle['sprites'].append(dict(name=name, png=path, decoded_size=list(extended.size), canvas=canvas))
        receipt['row_times'][f'launch_{view}'] = evidence['row_times'][view]
    receipt['shared_lift'] = evidence
    manifest['held_pose_rows'] = [item for item in manifest['held_pose_rows'] if item['row'] != 'launch']
    (packet_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


def add_shared_walk(spec, packet_dir, manifest, receipt):
    """Add bank 1's 11/17 walk as an explicit 'walksrc' row, on the body canvas extended to fit.

    It goes in its own row rather than replacing the held 'walk' row: the donor's walk cells are
    shared with the neighbouring animations (21/41/31), so ownanim binds these frames to D5 11/17
    key by key instead of letting the sheet matching re-dress those animations.
    """
    from PIL import Image
    from d5lib import d1cart
    result = d1cart.shared_walk(bb.ART, manifest['body'])
    if result is None:
        raise ValueError('Shared walk bank 1 is missing')
    walk, evidence = result
    old = receipt['canvas']['bounds']
    bounds = evidence['bounds']
    union = [min(old[0], bounds[0]), min(old[1], bounds[1]),
             max(old[2], bounds[2]), max(old[3], bounds[3])]
    canvas = [int(old[3]-old[1]), int(old[2]-old[0]),
              int(old[1]-union[1]), int(old[0]-union[0])]
    for bundle in manifest['bundles']:
        view = bundle['label']
        for n, image in enumerate(walk[('walk', view)]):
            extended = Image.new('RGBA', (int(union[2]-union[0]), int(union[3]-union[1])))
            extended.paste(image, (int(bounds[0]-union[0]), int(bounds[1]-union[1])))
            name = f'walksrc{n+1:02d}'
            path = f'{view}/{name}.png'
            extended.save(packet_dir / path)
            bundle['sprites'].append(dict(name=name, png=path, decoded_size=list(extended.size), canvas=canvas))
        receipt['row_times'][f'walksrc_{view}'] = evidence['row_times'][view]
    receipt['shared_walk'] = evidence
    manifest['held_pose_rows'] = [item for item in manifest['held_pose_rows'] if item['row'] != 'walk']
    (packet_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

def add_shared_damage(spec, packet_dir, manifest, receipt):
    """Add bank 1's 1031/1037 hurt reaction as an explicit 'dmgsrc' row, on the body canvas extended to fit.

    D5's hurt slot is pose base 2 (motion 21/27, script event 15092305). The source reaction is bound
    to that slot after sheet matching, so no other animation is re-dressed by these frames.
    """
    from PIL import Image
    from d5lib import d1cart
    result = d1cart.shared_damage(bb.ART, manifest['body'])
    if result is None:
        raise ValueError('Shared damage bank 1 is missing')
    damage, evidence = result
    old = receipt['canvas']['bounds']
    bounds = evidence['bounds']
    union = [min(old[0], bounds[0]), min(old[1], bounds[1]),
             max(old[2], bounds[2]), max(old[3], bounds[3])]
    canvas = [int(old[3]-old[1]), int(old[2]-old[0]),
              int(old[1]-union[1]), int(old[0]-union[0])]
    for bundle in manifest['bundles']:
        view = bundle['label']
        for n, image in enumerate(damage[('damage', view)]):
            extended = Image.new('RGBA', (int(union[2]-union[0]), int(union[3]-union[1])))
            extended.paste(image, (int(bounds[0]-union[0]), int(bounds[1]-union[1])))
            name = f'dmgsrc{n+1:02d}'
            path = f'{view}/{name}.png'
            extended.save(packet_dir / path)
            bundle['sprites'].append(dict(name=name, png=path, decoded_size=list(extended.size), canvas=canvas))
        receipt['row_times'][f'dmgsrc_{view}'] = evidence['row_times'][view]
    receipt['shared_damage'] = evidence
    (packet_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


def rebuild(spec, plan, work, rows, table_sha, shared_lift=False, shared_walk=False,
            shared_damage=False, attack_track=False, sprite_shape=None, attack_max_frames=None):
    work = Path(work)
    packet_dir = work / 'prepared'
    if packet_dir.exists():
        import shutil
        shutil.rmtree(packet_dir)
    manifest, receipt = bb.prepare(spec, packet_dir)
    if shared_lift or shared_walk or shared_damage:
        if spec['kind'] != 'humanoid':
            raise ValueError('Shared bank motions require a humanoid body')
    if shared_lift:
        add_shared_lift(spec, packet_dir, manifest, receipt)
    if shared_walk:
        add_shared_walk(spec, packet_dir, manifest, receipt)
    if shared_damage:
        add_shared_damage(spec, packet_dir, manifest, receipt)
    source = bb.source_packet(spec, rows, table_sha, plan)
    # the lane's help line uses an em dash; the kit's R7 gate now requires ASCII in the Latin slots
    # (the built packs were fixed afterwards).  Art rebuild only: the text is not shipped.
    source['help_lines'] = [line.replace('\u2014', '-') for line in source['help_lines']]
    faces, cutins = bb.screen_art(packet_dir, manifest)
    output = work / 'out'
    if output.exists():
        import shutil
        shutil.rmtree(output)
    sprites.CACHE_DIR = str(output) + '.cache'
    nativeimports.build_entry(
        source=source, prepared_root=packet_dir, library_root=packet_dir / 'library',
        game_path=bb.GAME, original_state=bb.STATE, output_path=output,
        mod_id=f"D1C_Class_{spec['registry']}", target=spec['registry'],
        physical=spec['physical'], template=spec['template'], kind=spec['kind'],
        face_paths=faces, cutin_paths=cutins,
        source_palettes=bb.palette_banks(manifest['body']),
        mods_roots=(), help_id=None, quest_id=None, quest_slot=None,
        unlocked_ranks=len(source['ranks']),
        approximate_palettes=True, log=lambda *a: None, whole_body=True,
        skills=plan['skills'], source_times=receipt.get('row_times'), attack_track=attack_track, sprite_shape=sprite_shape, attack_max_frames=attack_max_frames)
    mod = output / 'native-mods' / f"D1C_Class_{spec['registry']}"
    receipt_path = output / 'source-import-receipt.json'
    anim = {}
    if receipt_path.exists():
        anim = json.loads(receipt_path.read_text()).get('animation', {})
    return mod, anim


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch', required=True, choices=['humanoids', 'monsters'])
    ap.add_argument('--only', type=int, action='append', required=True)
    ap.add_argument('--work', required=True)
    ap.add_argument('--shared-lift', action='store_true')
    ap.add_argument('--shared-walk', action='store_true')
    ap.add_argument('--shared-damage', action='store_true')
    ap.add_argument('--pin-shape', action='store_true',
                    help='MONATK1: give the rebuilt bank the installed bank\'s atlas page / palette count (wheel gate)')
    ap.add_argument('--attack-frames', type=int, default=None, help='MONATK1: at most this many source frames per attack view')
    ap.add_argument('--attack-track', nargs='?', const='2071,2077', default=None,
                    help='MONATK1: put the source attack frames on these animation ids (default 2071,2077)')
    args = ap.parse_args()
    from d5lib.importers import _d1c_source
    _d1c_source.use(_d1c_source.data())          # the verified prepared source folder
    from d5lib import modsys, paths
    game = Path(paths.require_game_dir())
    bb.configure(game, modsys.game_state_dir(str(game), str(KIT)))
    doc = dict(classes=bb.class_specs())
    plan_doc = dict(classes=bb.skills_plan())
    rows, table_sha = bb.table_rows()
    out = {}
    for registry in args.only:
        spec = next(s for s in doc['classes'] if s['registry'] == registry)
        work = Path(args.work) / str(registry)
        shape = None
        if args.pin_shape:
            from d5lib import anm, gamefs
            inst = anm.parse(gamefs.GameFS(str(bb.GAME)).read(f"Anime/ANM_HI_JP.dat/anm{spec['physical']:05d}.lzs"))
            shape = (len(inst.textures), len(inst.palettes))
        mod, anim = rebuild(spec, plan_doc['classes'][str(registry)], work, rows, table_sha,
                            shared_lift=args.shared_lift, shared_walk=args.shared_walk,
                            shared_damage=args.shared_damage, attack_track=tuple(int(x) for x in args.attack_track.split(',')) if args.attack_track else False, sprite_shape=shape, attack_max_frames=args.attack_frames)
        out[str(registry)] = dict(mod=str(mod), retime=anim.get('source_paced_retime'),
                                  rotations=anim.get('source_frame_fallbacks') and None,
                                  anchors=sorted({v.get('anchored') for v in (anim.get('matches') or {}).values()
                                                  if isinstance(v, dict)}))
        print(registry, spec['name'], 'rebuilt ->', mod, flush=True)
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
