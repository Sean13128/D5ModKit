"""Rebuild shipped DD2 packs with the native prepared-source and hybrid-track recipes.

The installed pack is read only for allocation leases and comparison. Every game
pixel/stat input is read from the original DD2 copy. The kit owns all emitted rows.
The hybrid conversion below retains the DD2GEN recipe (source/shared_tracks).

SOURCEPREP4-DD2: the game copy comes from the prepared source folder through
``_dd2_source.data_dir`` (never a machine path); ids and frozen rules live in
checked-in data files; the Character Forge reader package is resolved explicitly
by ``_dd2_source.forge_root``.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
from ..importcore import Entry
from . import _dd2_prepare as prep
from . import _dd2_source as sources

KIT = Path(__file__).resolve().parents[2]
LEASES = Path(__file__).with_name('dd2-leases.json')
PYTHON = sys.executable
ALIASES = {41:21,47:27,1561:1,1567:7,1571:1,1577:7,1581:1,1587:7,1591:1,1597:7,1601:1,1607:7,7001:1,7007:7,7011:1051,7021:2001}


def leases():
    return json.loads(LEASES.read_text())['entries']


def source_data(root=None):
    """The DD2 ``Data`` folder; ``root`` is an explicit dump root (CLI/tests), else the prepared source."""
    return sources.data_dir(root)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def roster(source_root=None):
    from ..dd2source import Nispack, Tables
    data = source_data(source_root)
    archive = data.path('START_4.dat')
    raw = archive.read_bytes()
    pack = Nispack(raw)
    table = pack.read('char.dat')
    tables = Tables(pack)
    rows = {}
    for index in range(struct.unpack_from('>H',table)[0]):
        start=4+index*676
        cid=struct.unpack_from('>H',table,start+0x194)[0]
        rows[cid]=(index,start,_sha(table[start:start+676]))
    entries=[]
    for folder, lease in leases().items():
        sid=lease['source_id']; index,offset,digest=rows[sid]
        entries.append(Entry(id=f"dd2:{'u' if lease['kind']=='unique' else ''}{sid}",
            kind=lease['kind'],name=tables.chars[sid]['name'],mod_folder=folder,
            in_scope=not lease.get('parked'),why_not=lease.get('why',''),
            source_ref=dict(file=str(archive),sha256=_sha(raw),member='char.dat',
                table_sha256=_sha(table),row=sid,row_index=index,row_offset=offset,
                row_sha256=digest,body=tables.chars[sid]['body'])))
    return entries


def source_facing_table(path,scratch):
    """The pinned shared-pose table without its back-view flips.

    The table was learned against reference art whose back views face the other way,
    but standing idles never pass through it, so applying the flip leaves a prepared
    back set half mirrored and detect_mirror can only get one half right. Source
    facing is what D5's poses match, so every back pose keeps it.
    """
    table=json.loads(Path(path).read_text())
    for pose in table['poses'].values(): pose['flip_x']=False
    out=Path(scratch); out.mkdir(parents=True,exist_ok=True)
    out=out/'source-facing-poses.json'; out.write_text(json.dumps(table))
    return out


def add_special_poses(folder,frames):
    """Add the source's own front special poses ({id: (frames, feet origin)}) to a prepared body as rows.

    d2art exports only the shared action cells and the standing idle, so 7001/7011 otherwise
    fall back to a stand. Returns {id: frames written}.
    """
    from d5lib.ownanim import SPECIAL_ROWS
    folder=Path(folder); path=folder/'manifest.json'; manifest=json.loads(path.read_text())
    front=next(b for b in manifest['bundles'] if b['label']=='front')
    written={}
    for aid,(images,origin) in sorted(frames.items()):
        if not images or aid not in SPECIAL_ROWS: continue
        row=SPECIAL_ROWS[aid]
        for n,image in enumerate(images,1):
            name=f'{row}{n:02d}'; image.save(folder/'front'/f'{name}.png')
            front['sprites'].append(dict(name=name,png=f'front/{name}.png',decoded_size=list(image.size),
                pivot=dict(x=origin[0]/image.width,y=1-origin[1]/image.height)))
        written[aid]=len(images)
    path.write_text(json.dumps(manifest,indent=2))
    return written


def _special_frames(raw,body,palette):
    from forge import d2art
    out={}
    for aid in (7001,7011):
        try: out[aid]=d2art.standing(raw,body,palette,(aid,))
        except ValueError: pass        # the body has no such animation
    return out


def source_tracks(raw,body,palette,special=()):
    """{6001/6007/7001: the source's own clock} for ownanim.build (DD2LEN1).

    Each drawn moment of the source animation becomes one key at the source's time, showing the
    prepared frame d2art cut from that moment: the 'wait' rows hold the unique standing frames
    (d2art.extract), the 'special' rows one frame per moment (add_special_poses).  The control
    keys are the source root's.  7001 only when its special frames were prepared (`special`).
    """
    from forge import d2art
    from .. import d2anm
    block=next(x for x in d2anm.parse(raw).blocks if x.id==body)
    t=d2art.tables(raw,body); tags,tracks,keys=t['tags'],t['tracks'],t['keys']
    out={}
    for aid,row in ((6001,'wait'),(6007,'wait'),(7001,'special')):
        animation=next((a for a in block.animations if a.id==aid),None)
        if animation is None or (row=='special' and aid not in special): continue
        # d2art.moments' own reading of the animation's draw moments
        i=next(i for i,(a,_) in enumerate(tags) if a==aid)
        lanes=[[k for k in keys[tr[4]:tr[4]+tr[5]] if k[1]==0]
               for tr in tracks[tags[i][1]:tags[i+1][1] if i+1<len(tags) else len(tracks)]
               if tr[4]!=0xFFFF and tr[4]+tr[5]<=len(keys)]
        times=sorted({k[0] for lane in lanes for k in lane if k[2]})
        frames=[f.tobytes() for f in d2art.standing(raw,body,palette,(aid,))[0]]
        if len(frames)!=len(times): raise ValueError(f'{body} {aid}: {len(times)} moments, {len(frames)} frames')
        numbers=[list(dict.fromkeys(frames)).index(f) for f in frames] if row=='wait' else range(len(frames))
        out[aid]=dict(row=row,keys=list(zip(times,numbers)),
                      control=[(k.time,k.flags) for k in block.node_keys(block.nodes[animation.root])])
    return out


def decode_dd2(raw):
    """A D2 bank (d5lib.d2anm, byte faithful) in the form hybrid() takes.

    d2anm already holds key and cell byte fields the way D5 reads them, and (DD2READ1) images and
    cells as D2 stores them: palettes whole (some are 256x4), DXT5 sheets (format 4) at 1 byte per
    pixel, the 16-byte cell rows of four effect banks read 16 apart.  DD2GEN's reader misread these
    three (ANMRT2-REPORT.md F1-F3); no current pack used them.  What D5 can take is decided by
    to_d5_images(), which hybrid() calls.  Padding is zero.
    Transforms keep D2's word order; hybrid() moves the pivot.  Node words 0-1 are
    rewritten as D5's node u32 (d2anm.d5_node_words); copied raw, D5 read the draw-mode
    bit as asset id 0x10000 and skipped the node's cell (DD2DRAW1).  Palette counts are rewritten as
    D5's i32 (d2anm.d5_palette_counts); copied raw, an attack overran the game's palette buffer (WRITEWATCH1).
    """
    from .. import d2anm
    bank=d2anm.parse(raw)
    for image in bank.textures+bank.palettes: image.pad=b''
    for block in bank.blocks: block.pad=b''
    bank.trailing=b''
    d2anm.d5_node_words(bank)
    d2anm.d5_palette_counts(bank)     # D2 count is a big-endian i32: copied raw D5 reads 0x01000000 (WRITEWATCH1)
    return bank


def to_d5_images(bank):
    """Fit a decode_dd2 bank's images to the shapes D5 banks hold (checked on 2,347 clean D5 banks:
    textures are indexed-8 or ARGB32, every palette is a 256x1 ARGB32 image; no D5 bank has a
    256x4 palette or a DXT5 sheet, and whether the game accepts them is untested).

    A palette longer than 256 colours (D2 ships 256x4) is cut to its first 256 colours, the
    colours cell palette numbers can reach.  A DXT5 sheet has no D5 form here and is refused.
    """
    from .. import anm
    for i,image in enumerate(bank.textures):
        if image.fmt[0] not in (anm.FMT_INDEXED8,anm.FMT_ARGB32):
            raise ValueError(f'DD2 ANM texture {i} is format {image.fmt[0]} (DXT5): D5 banks hold none')
    for image in bank.palettes:
        image.width,image.height,image.data=256,1,image.data[:1024]
    return bank


def add_donor_slots(block,dblock):
    """Give the import's block every motion id the donor block has and the import lacks.

    A donor node index means nothing in the import's node table, so a slot never takes the
    donor's root: an attachment or 80xx slot gets its own empty root, an alias the import
    motion's root.  (The donor's 1011/1017 root indices landed inside the import's idle,
    where _fixed_passes then wrote a hold code onto the idle's first layer key: DD2ROOT1.)
    """
    from .. import anm,ownanim
    original={a.id for a in block.animations}
    attachments=ownanim.donor_attachments(dblock)

    def empty_root():
        block.nodes.append(anm.Node(0,0,0,0,0,0,-1,0,-1,-1))
        return len(block.nodes)-1
    for aid in sorted({a.id for a in dblock.animations}-original):
        if aid in attachments:
            block.animations.append(anm.Animation(aid,empty_root()))
        elif aid in ALIASES and any(a.id==ALIASES[aid] for a in block.animations):
            block.animations.append(anm.Animation(aid,next(a.root for a in block.animations if a.id==ALIASES[aid])))
        elif 1000 <= aid < 2000:
            # DD2GEN's final normalisation puts the donor's 10xx wait/action
            # slots in the installed 80xx private range.  No D5 skill plays
            # motion 801 (kit choreo), so the slot only has to exist.
            target = 8000 + aid % 1000
            if not any(a.id == target for a in block.animations):
                block.animations.append(anm.Animation(target, empty_root()))
        else:
            da=next(a for a in dblock.animations if a.id==aid); info=anm.animation_info(dblock,da)
            if aid==8000 and info['layers']==0 and info['control']==[(0,5)]:
                ki=len(block.keys); block.keys.append(anm.Key(0,5,0,0,0,0))
                ni=len(block.nodes); block.nodes.append(anm.Node(0,4096,0,0,0,0,ki,1,-1,-1))
                block.animations.append(anm.Animation(aid,ni))
            else: raise ValueError(f'Unsupported DD2GEN donor motion {aid}')
    block.animations.sort(key=lambda a:a.id)


def hybrid(body_raw,common_raw,donor,bank):
    from .. import anm,d2anm,dd2source,standground
    from tools.anim_prototype.shared_tracks import build as shared
    from tools.anim_prototype.source_tracks import build as monster
    body=to_d5_images(decode_dd2(body_raw)); common=to_d5_images(decode_dd2(common_raw))
    for source in (body,common): d2anm.swap_pivots(source)
    out=shared(body,common,bank_id=bank) if body.blocks[0].id==1210 else monster(body,bank_id=bank)
    block=out.blocks[0]; add_donor_slots(block,donor.blocks[0])
    if body.blocks[0].id==1210:
        for aid,src in ((1001,1),(1007,7)):
            next(a for a in block.animations if a.id==aid).root=next(a.root for a in block.animations if a.id==src)
    dd2source.drop_unresolved_attachments(out)
    dd2source.normalize_control_flags(out); dd2source.normalize_image_byte_order(out)
    out=anm.parse(out.to_bytes())
    standground.normalize_stand_ground(out,donor,log=lambda *a:None)
    return out


def _face(data,prepare,sid,rank,out):
    """Read the native face selector and exact atlas cell from the original game."""
    from PIL import Image
    from forge import nisfiles
    char,_=prepare.archive_member(data,'START','char.dat')
    table={struct.unpack_from('>H',char,4+i*676+0x194)[0]:4+i*676 for i in range(struct.unpack_from('>H',char)[0])}
    selector=struct.unpack_from('>H',char,table[sid]+0x19e)[0]
    # The selector is the pure mapping lifted out of forge/illustrations.py (see
    # _dd2_prepare.d2_face_location); the rest of that module pulls unrelated decoders.
    location=prep.d2_face_location(selector)
    if location is None: raise ValueError(f'No native source face for {sid}')
    stored,_=prepare.archive_member(data,'START',prep.face_bank(location))
    raw=nisfiles.expand(b'dat\0'+stored[4:])
    w,h=struct.unpack_from('>HH',raw,4)
    if len(raw)!=16+w*h*4: raise ValueError('Source face atlas byte size')
    image=Image.frombytes('RGBA',(w,h),raw[16:],'raw','ARGB')
    column=min(rank,w//96-1); y=location[1]*96
    crop=image.crop((column*96,y,(column+1)*96,y+96))
    # DD2GEN's opaque white matte was a deliberate fix pass.
    if sid>=1000:
        matte=Image.new('RGBA',crop.size,'white'); matte.alpha_composite(crop); crop=matte.convert('RGB')
    path=out/f'face-{sid}-{rank}.png'; crop.save(path); return str(path)


def _screen(data,prepare,art_id,path,*,page=False):
    from forge import nisfiles,d2art
    raw=nisfiles.expand(prepare.archive_member(data,'ANM_HI',f'anm{art_id:05d}.lzs')[0])
    image=next(iter(d2art.pages(raw,0).values())) if page else d2art.standing(raw,art_id,0,wanted=(1,))[0][0]
    image.save(path)
    return str(path)


def _cutin_cell(raw,art_id,image):
    """DD2CUTIN1: the page image cropped to the cell the game draws (motion 8000: 125x544 at x=1 in the 128x544 page).
    The page keeps the cell's border columns, which the game never draws (DD2-SPR-07, Tools/source_readers/dd2/pictures.py)."""
    from forge import d2art
    rects=[r[4:8] for r in d2art.tables(raw,art_id)['rects'] if r[6]>0 and r[7]>0]
    if not rects: return image
    x,y,w,h=max(rects,key=lambda r:r[2]*r[3])
    return image.crop((x,y,x+w,y+h))


def _cutin(data,prepare,art_id,path,*,cell):
    """The cut-in picture of source art id `art_id`: the whole page (the historical input) or, with `cell`, the drawn cell."""
    from forge import nisfiles,d2art
    raw=nisfiles.expand(prepare.archive_member(data,'ANM_HI',f'anm{art_id:05d}.lzs')[0])
    image=next(iter(d2art.pages(raw,0).values()))
    if cell: image=_cutin_cell(raw,art_id,image)
    image.save(path)
    return str(path)


def _worker(config):
    sys.path.insert(0,str(config['forge_root']))
    import numpy.testing
    from forge import nisfiles
    from forge.backend.d2_character_export import anm_pages
    from .. import anm,dd2source,nativeimports,newclasses,ownanim,sprites,runtime,modsys
    from d5lib.importers.dd2 import original_fs
    # The parent resolved one verified input set; the child opens exactly that set, never the folder.
    data = (sources.Dd2Data.from_config(config['source_data']) if config.get('source_data')
            else source_data(config.get('source_root')))
    lease=config['lease']; sid=lease['source_id']; out=Path(config['out']); scratch=out/'inputs'; scratch.mkdir(parents=True)
    rows=prep.read_selected(data,[sid]); sample=rows[0]
    prepared=scratch/'prepared'
    prep.prepare(rows,data,prepared,source_facing_table(sources.pose_table(),scratch) if sample['body_kind']=='humanoid' else None)
    tracks=None
    if sample['body_kind']=='humanoid':
        special=add_special_poses(prepared/str(sid),_special_frames(sample['_body_raw'],sample['body'],sample['palette']))
        tracks=source_tracks(sample['_body_raw'],sample['body'],sample['palette'],special)
    tables=dd2source.Tables(dd2source.Nispack(data.path('START_4.dat').read_bytes()))
    ranks=sample['source_rank_profiles'] if lease['kind']=='class' else [sample['profile']]
    for rank in ranks: rank['title']=tables.chars[rank['id']]['title']
    if config.get('source_fields', True):
        # DD2FIELDS1: the battle block of the source row (MOV, JMP, throw, counter, crit, range, flying, resistances,
        # weapon aptitudes, kind/gender, immunity) instead of the D5 donor's; provenance per field goes to mod.json.
        for rank in ranks:
            rank['battle_fields'],rank['battle_provenance']=tables.battle(rank['id'])
    packet=dict(game='dd2',edition=sample['edition'],name=sample['name'],ranks=ranks,
        rank_palette_bindings=sample['rank_palette_bindings'][:len(ranks)],help_lines=tables.help_text(sid))
    if isinstance(packet['help_lines'],str): packet['help_lines']=packet['help_lines'].splitlines()
    # Native prepared-source builds leave abilities blank except the two original
    # DD2 continuation characters whose D5 aliases were already emitted (frozen
    # rows in d5lib/importers/dd2-baseline-configs.json, formerly codex/ configs).
    orig_cfg=sources.baseline_config(sid) if lease['kind']=='unique' else None
    if orig_cfg:
        for key in ('skills','evilities'):
            if orig_cfg.get(key): packet[key]=orig_cfg[key]
        for rank,old in zip(packet['ranks'],orig_cfg['ranks']):
            for key in ('learn','evilities'):
                if key in old: rank[key]=old[key]
    decoded=anm_pages(sample['_body_raw'],include_rgba=False,palette_indices=list(range(sample['palettes'])))
    banks={}
    for p in decoded: banks.setdefault(p['palette'],p['colors'])
    palettes=[banks[i] for i in range(sample['palettes'])]
    palettes.extend([palettes[-1]]*(10-len(palettes)))
    faces=[_face(data,prep,sid,k,scratch) for k in range(6 if lease['kind']=='class' else 1)]
    # The native writer requires a source-backed illustration input even when
    # the installed pack's final file set does not materialize a cut-in.  The
    # proven 10000+source-id illustration members are indexed DD2 pages; use
    # those rather than the separately formatted dialogue-atlas members.
    if config.get('cutin_fit',True):
        # DD2CUTIN1: the drawn 125x544 cell, placed with one scale on the D5 strip (nativeimports cutin_fit='contain'),
        # and for a class each rank's own strip (source art 10000+id+rank, DD2-SPR-07); a rank without one keeps rank 0's.
        cutins=[]
        for k in range(6 if lease['kind']=='class' else 1):
            try: cutins.append(_cutin(data,prep,10000+sid+k,scratch/f'cutin_{k}.png',cell=True))
            except ValueError:
                if k==0: raise
                cutins.append(cutins[0])
    else:
        cutins=[_screen(data,prep,10000+sid,scratch/'cutin.png',page=True)]
    build=out/'builder'; cache=out/'builder.cache'; sprites.CACHE_DIR=runtime.CACHE=str(cache)
    modsys.load_handlers()
    kwargs=dict(source=packet,prepared_root=str(prepared/str(sid)),library_root=str(prepared/'library'),
        game_path=config['game_path'],original_state=config['state_root'],output_path=str(build),
        mod_id=config['folder'],target=lease['target'],physical=lease['physical'],template=lease['template'],
        kind=lease['body_kind'],face_paths=faces,cutin_paths=cutins,source_palettes=[[list(c) for c in b] for b in palettes],
        mods_roots=[],unlocked_ranks=len(ranks),log=lambda *a:None,
        approximate_palettes=lease['kind']=='class' or lease['kind']=='unique',
        exact_palette_banks=sid in (10,30,50,60,100,140) and lease['kind']=='unique',source_tracks=tracks,
        cutin_fit='contain' if config.get('cutin_fit',True) else 'stretch')
    if config.get('source_fields', True) and lease['kind']=='unique' and sample['palette']:
        # DD2FIELDS1: the art is extracted in the row's palette (Virunga 5), so look its colours up in that bank and
        # make it the default slot; before, bank-5 colours found no match in bank 0 and every slot became bank 0.
        kwargs.update(source_base_bank=sample['palette'],default_palette=sample['palette'])
    if lease['kind']=='unique': kwargs.update(help_id=lease['help'],quest_id=lease['quest'],quest_slot=lease['quest_slot'])
    nativeimports.build_entry(**kwargs)
    pack=build/'native-mods'/config['folder']
    notes=[]
    if tracks:
        # The source clock shows every source idle frame, which can need another atlas page.
        # An added image header breaks the wheel-freeze rule, so such a pack keeps the template clock.
        from ..importcore import wheel_gate
        # SOURCEPREP4-DD2: the default build freezes against the recorded shape table, never the
        # installed pack; a comparison against the install is an explicit, read-only opt-in.
        installed = None
        if config.get('installed_reference') and config.get('installed_root'):
            installed = Path(config['installed_root'])/config['folder']
        ok,why=wheel_gate(pack,installed,reference=sources.wheel_reference(config['folder']))
        if not ok:
            shutil.rmtree(build); shutil.rmtree(cache,ignore_errors=True)
            nativeimports.build_entry(**dict(kwargs,source_tracks=None))
            notes.append(f'DD2LEN1 source clock not applied ({why}); 6001/6007/7001 keep the template timing.')
    if lease['kind']=='class':
        fs=original_fs(dict(game_path=Path(config['game_path']),state_root=Path(config['state_root'])))
        try:
            donor=anm.parse(fs.read(sprites.sprite_vpath(fs,lease['template'],'EN')))
            motion=sprites.motion_block(fs,1,lambda *a:None) if sprites.needs_motion_set(donor) else None
            if motion:
                # ``motion_block`` returns the resident block, while
                # ``bind_motion_set`` takes an AnmFile containing that block
                # followed by the donor sprite file.
                donor=anm.bind_motion_set(anm.AnmFile([motion], [], []),0,donor)
            common=nisfiles.expand(prep.archive_member(data,'ANM_HI','anm00001.lzs')[0])
            body=hybrid(sample['_body_raw'],common,donor,lease['physical'])
            path=pack/'files/Anime/ANM_HI_JP.dat'
            (path/f"anm{lease['physical']:05d}.lzs").write_bytes(anm.lzs_compress(body.to_bytes()))
            companion=newclasses.monster_companion(fs,body,lease['template'],lease['physical']) if lease['body_kind']=='monster' else ownanim.with_id(body,lease['physical']+1)
            (path/f"anm{lease['physical']+1:05d}.lzs").write_bytes(anm.lzs_compress(companion.to_bytes()))
        finally: fs.reset()
    # The shipped DD2 packs carry three old ability fix passes (the class
    # alias rows and the two named-character special rows).  They are frozen
    # lease definitions, not source inputs: preserve those definitions from the
    # checked-in data file so a rebuild does not silently drop them, and so a
    # machine without an installed pack builds the same rows.  The
    # reviewed-abilities flag adds a separate, newer ability set afterwards.
    # The frozen rows carry ids and sha256 text references only.  Resolve the text from the user's
    # own prepared DD2 archives and Disgaea 5 tables, exactly as the installed pack spelled it.
    fs = original_fs(dict(game_path=Path(config['game_path']),state_root=Path(config['state_root'])))
    try:
        pool = sources.TextPool.from_game(data, fs)
    finally:
        fs.reset()
    _fixed_passes(pack,lease,data,sources.frozen_patches(config['folder'], text=pool.get))
    dest=out/'native-mods'/config['folder']; dest.parent.mkdir(exist_ok=True); shutil.move(str(pack),dest)
    receipt=dict(source_pin=config['source_ref'],lease=lease,notes=['Replayed nativeimports and DD2GEN hybrid source tracks; source art/stat inputs decoded from the prepared DD2 source folder.']+notes,features={})
    (out/'baseline-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    # Prepared frames, duplicate materialization and caches are disposable, not candidate packs.
    shutil.rmtree(build); shutil.rmtree(scratch); shutil.rmtree(cache,ignore_errors=True)


def _fixed_passes(pack,lease,data,frozen=None):
    from .. import anm,dd2source
    charpath=pack/'patches/db/char.dat.json'; doc=json.loads(charpath.read_text())
    for i,row in enumerate(doc.get('added',[])):
        row['voice_id']=lease['voice_ids'][i]; row['help_id']=lease['help']
    # Masked Hero's exact source mastery pass, omitted DD2 book type.
    if lease['source_id']==1210:
        from ..dd2source import Nispack
        raw=Nispack(data.path('START_4.dat').read_bytes()).read('char.dat')
        for row,sid in zip(doc['added'],lease['source_rank_ids']):
            original=next(raw[4+i*676:4+(i+1)*676] for i in range(struct.unpack_from('>H',raw)[0]) if struct.unpack_from('>H',raw,4+i*676+0x194)[0]==sid)
            for key,value in zip(('fist','sword','spear','bow','gun','axe','staff'),original[0x27c:0x283]): row['mastery_'+key]=value
    charpath.write_text(json.dumps(doc,ensure_ascii=False,indent=1)+'\n')
    hp=pack/'patches/db/charhelp.dat.json'; helpdoc=json.loads(hp.read_text())
    for row in helpdoc.get('added',[]): row['id']=lease['help']; row['char_id']=lease['help']
    hp.write_text(json.dumps(helpdoc,ensure_ascii=False,indent=1)+'\n')
    pp=pack/'patches/db/charPersonal.dat.json'
    if pp.exists():
        personal=json.loads(pp.read_text()); rows=personal.get('added',[])
        if len(rows)!=len(lease['personalities']): raise ValueError('Personality lease count drift')
        for row,pid in zip(rows,lease['personalities']): row['id']=pid
        pp.write_text(json.dumps(personal,ensure_ascii=False,indent=1)+'\n')
    if lease['kind']=='class':
        sp=next((pack/'patches/classes').glob('*.json')); spec=json.loads(sp.read_text()); spec['wheel']='dd2'
        sp.write_text(json.dumps(spec,ensure_ascii=False,indent=1)+'\n')
        mp=pack/'mod.json'; meta=json.loads(mp.read_text()); meta['wheel']='dd2'; mp.write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    for path in (pack/'files').rglob('*.lzs'):
        bank=anm.load(path); dd2source.normalize_control_flags(bank)
        # DD2WHEEL6's final pass also gave source-only monster roots an
        # explicit hold marker.  Some prepared monster roots have no high-byte
        # marker to move, so the generic normalizer alone cannot repair them.
        for block in bank.blocks:
            for animation in block.animations:
                if not (0 <= animation.root < len(block.nodes)):
                    continue
                keys = block.node_keys(block.nodes[animation.root])
                if keys and not any(key.flags & 0xFF for key in keys):
                    keys[0].flags = 5
        dd2source.normalize_image_byte_order(bank)
        blank_missing_pages(bank)
        path.write_bytes(anm.lzs_compress(bank.to_bytes()))
    if frozen:
        ids = set(frozen.get('reviewed_evility_ids') or ())
        for rel, text in sorted((frozen.get('files') or {}).items()):
            dst = pack / rel
            if dst.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text, encoding='utf-8')
            _drop_reviewed_rows(dst, rel, ids)


def drop_reviewed_evilities(reference, path, rel):
    """DD2-FIX1.5b: the reference's reviewed-ability evility rows are not baseline content.

    A reference that carries the reviewed layer (COREDD2-ABILITIES.json, ``added_evility_ids``) has those
    rows in the Skill/alias/evility patches this step copies; apply_reviewed regenerates them and then
    refuses its own leases as already occupied by the pack.  Drop them from the copy, keep everything else.

    Kept for callers/tests that still hold an installed reference on disk; the build itself uses the
    checked-in ``dd2-frozen-patches.json`` through ``_drop_reviewed_rows``."""
    receipt = Path(reference) / 'COREDD2-ABILITIES.json'
    if not receipt.is_file():
        return 0
    ids = {int(i) for i in json.loads(receipt.read_text()).get('added_evility_ids', [])}
    return _drop_reviewed_rows(path, rel, ids)


def _drop_reviewed_rows(path, rel, ids):
    if not ids:
        return 0
    doc, n = json.loads(Path(path).read_text()), 0
    if rel.endswith('Skill.dat.json'):
        rows = doc.get('added', [])
        doc['added'] = [r for r in rows if int(r.get('id', -1)) not in ids]
        n = len(rows) - len(doc['added'])
        for k in [k for k in doc.get('rows', {}) if int(k) in ids]:
            del doc['rows'][k]
            n += 1
    elif rel.endswith('aliases.json'):
        for k in [k for k in doc if str(k).isdigit() and int(k) in ids]:
            del doc[k]
            n += 1
    elif rel.endswith('evilities.json') and isinstance(doc.get('evilities'), dict):
        for k in [k for k in doc['evilities'] if int(k) in ids]:
            del doc['evilities'][k]
            n += 1
    if n:
        Path(path).write_text(json.dumps(doc, indent=1, ensure_ascii=False) + '\n')
    return n


def blank_missing_pages(bank):
    """DD2-FIX1.7 (the D4CELL1 rule): zero cells that index a texture page the bank does not have.

    The merged shared block keeps cells for pages 9-16 (144 key-drawn cells in Masked Hero's bank, nodes
    31/21/1); a 9-page body has no art there, and once the installer's banner_layout repack adds pages
    they draw unrelated art.  Same index kept, rectangle zeroed (a w=0 cell draws nothing).  Only a
    missing page is blanked, a cell running past the edge of an existing page is left (vanilla ships those)."""
    from .. import anm
    n = 0
    for block in bank.blocks:
        pages = len(block.texture_infos) if len(bank.blocks) > 1 else len(bank.textures)
        for i, c in enumerate(block.cells):
            if c.w and c.h and c.tex >= pages:
                block.cells[i] = anm.Cell(0, c.pal, c.unk2, c.flags, 0, 0, 0, 0, c.unk8)
                n += 1
    return n


def build_baseline(entry,out_dir,ctx):
    out=Path(out_dir); out.mkdir(parents=True,exist_ok=True)
    if (out/'native-mods'/entry.mod_folder).exists(): raise FileExistsError('Output pack already exists')
    data = source_data(ctx.get('source_root'))
    config=dict(folder=entry.mod_folder,lease=leases()[entry.mod_folder],source_ref=entry.source_ref,
                source_root=str(data.root),source_data=data.to_config(),out=str(out),game_path=str(ctx['game_path']),
                state_root=str(ctx['state_root']),installed_root=str(ctx.get('installed_root') or ''),
                installed_reference=bool(ctx.get('installed_reference', True)),
                forge_root=str(sources.forge_root()),
                source_fields=bool((ctx.get('options') or {}).get('dd2_source_fields', True)),
                cutin_fit=bool((ctx.get('options') or {}).get('dd2_cutin_fit', True)))
    cp=out/'baseline-config.json'; cp.write_text(json.dumps(config,indent=2)+'\n')
    code='import json,sys; from d5lib.importers._dd2_baseline import _worker; _worker(json.load(open(sys.argv[1])))'
    env=dict(os.environ)
    # Keep a caller's PYTHONPATH (the SOURCEPREP1 read tracer rides on it) and put the kit first.
    env['PYTHONPATH']=os.pathsep.join([str(KIT)]+[p for p in [env.get('PYTHONPATH')] if p])
    env['PYTHONDONTWRITEBYTECODE']='1'
    with (out/'build.log').open('w') as log:
        proc=subprocess.run([str(PYTHON),'-c',code,str(cp)],cwd=KIT,env=env,stdout=log,stderr=subprocess.STDOUT)
    if proc.returncode: raise RuntimeError(f"DD2 builder exit {proc.returncode}; see {out/'build.log'}")
    return out/'native-mods'/entry.mod_folder,json.loads((out/'baseline-receipt.json').read_text())


def compare_reason(entry,diff):
    return 'Source provenance re-pinned; current native Kit writer and original DD2GEN/DD2NAMED recipes replayed.'
