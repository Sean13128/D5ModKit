"""Compare every sampled ANM pose and rank against a baseline using the kit renderer.

Sample times are the union of both files' renderer frame_times for each animation. `--exempt` names
the animation IDs whose samples may differ (default: the four lift IDs; D1CWALK1 passes 11 17 and
leaves the lift inside the equality check). Outputs a JSON receipt and a side-by-side PNG for every
differing non-exempt sample.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from d5lib import anm, grips, ownanim

LIFT = {1061, 1067, 1141, 1147}


def read(path):
    data = Path(path).read_bytes()
    return anm.load(data), hashlib.sha256(data).hexdigest()


def replay_member(data, passes):
    """Replay selected member-local finalizers in installer order.

    The caller must establish which passes apply. Companion regeneration, palette
    sync and other profile-dependent edits require materialized installed members.
    Preserve input bytes when a finalizer does not write.
    """
    a = anm.load(data)
    if passes == 'banner,grips' and ownanim.banner_layout(a):
        data = a.to_bytes()
        a = anm.load(data)
    if passes in ('grips', 'banner,grips') and grips.hide_at_rest(a):
        data = a.to_bytes()
    return data


def pose(a, idx, t, rank):
    items = anm.evaluate(a, idx, t, nested=True)
    image, origin = anm.render_items(a, items, palette_index=rank)
    bbox = image.getchannel('A').getbbox()
    if not bbox:
        return Image.new('RGBA', (1, 1)), None
    # Position of the alpha-content corner in the coordinate system of the pivot.
    position = (bbox[0] - origin[0], bbox[1] - origin[1])
    return image.crop(bbox), position


def save_pair(left, right, path, label, left_label):
    w = max(left.width, right.width, 150)
    h = max(left.height, right.height, 20)
    out = Image.new('RGBA', (2 * w, h + 30), (48, 48, 48, 255))
    out.alpha_composite(left, (0, 30))
    out.alpha_composite(right, (w, 30))
    draw = ImageDraw.Draw(out)
    draw.text((2, 2), f'{left_label} {label}', fill='white')
    draw.text((w + 2, 2), 'REBUILT', fill='white')
    out.convert('RGB').save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('baseline')
    ap.add_argument('rebuilt')
    ap.add_argument('output', help='receipt JSON path; mismatch PNGs are written beside it')
    ap.add_argument('--ranks', type=int, default=6)
    ap.add_argument('--exempt', type=int, nargs='*', default=sorted(LIFT),
                    help='animation IDs allowed to differ (default: the four lift IDs)')
    ap.add_argument('--baseline-label', default='BASELINE')
    ap.add_argument('--expect-extra', type=int, nargs='*', default=[],
                    help='animation IDs the rebuilt pack is expected to add (e.g. a preserved copy)')
    ap.add_argument('--baseline-sha256', nargs='*', default=[],
                    help='TEST28 sha256 the baseline file must have; the gate fails if it is not one of these')
    ap.add_argument('--post-install', action='store_true',
                    help='replay explicitly selected member-local installer finalizers on both inputs')
    ap.add_argument('--confirm-member-local', action='store_true',
                    help='attest neither input requires companion regeneration, palette sync or other unlisted passes')
    for side in ('baseline', 'rebuilt'):
        ap.add_argument(f'--{side}-passes', choices=('none', 'grips', 'banner,grips'),
                        help='known passes for this member; choose explicitly in --post-install mode')
    args = ap.parse_args()
    if args.post_install != (args.baseline_passes is not None and args.rebuilt_passes is not None):
        ap.error('--post-install requires both --baseline-passes and --rebuilt-passes; '
                 'pass selections require --post-install')
    if args.post_install and not args.confirm_member_local:
        ap.error('post-install replay requires --confirm-member-local; materialize installed members if other passes apply')
    if not args.post_install and (args.confirm_member_local or args.baseline_passes is not None or args.rebuilt_passes is not None):
        ap.error('pass selections require --post-install')
    exempt = set(args.exempt)
    old, old_hash = read(args.baseline)
    new, new_hash = read(args.rebuilt)
    replay = None
    if args.post_install:
        old_data = replay_member(Path(args.baseline).read_bytes(), args.baseline_passes)
        new_data = replay_member(Path(args.rebuilt).read_bytes(), args.rebuilt_passes)
        old, new = anm.load(old_data), anm.load(new_data)
        replay = dict(baseline_passes=args.baseline_passes, rebuilt_passes=args.rebuilt_passes,
                      baseline_member_sha256=hashlib.sha256(old_data).hexdigest(),
                      rebuilt_member_sha256=hashlib.sha256(new_data).hexdigest())

    def indexes(a):
        infos = anm.list_animations(a)
        ids = [x['id'] for x in infos]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate animation IDs require disambiguation')
        return {x['id']: x['index'] for x in infos}

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    baseline_pin = sorted(set(args.baseline_sha256))
    if baseline_pin and old_hash not in baseline_pin:
        raise SystemExit(f'refusing baseline {args.baseline}: sha256 {old_hash} is not the '
                         f'pinned TEST28 bank {baseline_pin}')
    structural = anm.compare_structure(old, new)
    structural_problems = structural['structural_problems']
    if structural_problems:
        receipt = dict(baseline=str(args.baseline), rebuilt=str(args.rebuilt),
                       baseline_sha256=old_hash, rebuilt_sha256=new_hash,
                       baseline_pin=baseline_pin, post_install_replay=replay, **structural,
                       samples_compared=0, pass_=False)
        receipt['pass'] = receipt.pop('pass_')
        output.write_text(json.dumps(receipt, indent=2) + '\n')
        print(f'FAIL: {len(structural_problems)} structural problems; rendering skipped')
        return 1
    oi, ni = indexes(old), indexes(new)
    receipt = dict(baseline=str(args.baseline), rebuilt=str(args.rebuilt),
                   baseline_sha256=old_hash, rebuilt_sha256=new_hash,
                   baseline_pin=baseline_pin, post_install_replay=replay, **structural,
                   rank_palettes=list(range(args.ranks)),
                   method='kit renderer, nested=True; union of frame_times; exact RGBA and alpha-bounds position relative to origin',
                   exempt_ids=sorted(exempt), lift_ids=sorted(LIFT),
                   missing_ids=sorted(oi.keys() - ni.keys()),
                   extra_ids=sorted(ni.keys() - oi.keys()),
                   expected_extra=sorted(set(args.expect_extra)),
                   animation_samples={},
                   samples_compared=0, exempt_samples=0, differences=[])
    for aid in sorted(oi.keys() & ni.keys()):
        times = sorted(set(anm.frame_times(old, oi[aid])) | set(anm.frame_times(new, ni[aid])))
        receipt['animation_samples'][str(aid)] = times
        for t in times:
            for rank in range(args.ranks):
                a, apos = pose(old, oi[aid], t, rank)
                b, bpos = pose(new, ni[aid], t, rank)
                receipt['samples_compared'] += 1
                if aid in exempt:
                    receipt['exempt_samples'] += 1
                    continue
                if a.size != b.size or a.tobytes() != b.tobytes() or apos != bpos:
                    name = f'{output.stem}-id{aid}-t{t}-rank{rank}.png'
                    save_pair(a, b, output.parent / name, f'{aid} t{t} rank{rank}', args.baseline_label)
                    receipt['differences'].append(dict(id=aid, time=t, rank=rank,
                        baseline_position=apos, rebuilt_position=bpos, baseline_size=a.size,
                        rebuilt_size=b.size, png=name))
        print(f'{aid}: {len(times)} times', flush=True)
    unexpected_extra = sorted(set(receipt['extra_ids']) - set(args.expect_extra))
    receipt['unexpected_extra'] = unexpected_extra
    receipt['pass'] = not (receipt['missing_ids'] or unexpected_extra or receipt['differences'])
    output.write_text(json.dumps(receipt, indent=2) + '\n')
    print(f"{'PASS' if receipt['pass'] else 'FAIL'}: {receipt['samples_compared']} samples, "
          f"{receipt['exempt_samples']} exempt, {len(receipt['differences'])} differences")
    return 0 if receipt['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
