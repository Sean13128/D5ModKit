"""Private process-isolated worker for :mod:`drpg`; no install operations."""
from __future__ import annotations
import hashlib
import importlib.util
import copy
import json
import os
import sys
import traceback
import tempfile
from pathlib import Path
from .drpg import KIT, PENDING_ART_LEASES, remove_created, record_created
from . import drpg_leases, _drpg_source, _drpg_text
from .. import database, dbpatch, drpg, drpgmap, gamefs, modsys, outfits, slots, sprites
from ..importcore import NO_YIELD_FIELD_NOTE, donor_yield, sha256, wheel_gate

_PLAN = {}
DB = 'Database/Database_0.dat/'
# DRPGCUTIN2 own cut-ins (<id>.png made by tools/make_drpg_own_cutins.py from the character's illustration) are an explicit
# opt-in folder (env D5_DRPG_OWN_CUTINS); the prepared source has no illustrations, so by default no such file is read.
OWN_CUTIN_PROVENANCE = 'illustration'
OWN_CUTIN_LABEL = "cut-in made from the character's own illustration; the source has no cut-in file for this look"


MONSTER_TEMPLATE = 2010     # the vanilla monster class a monster look is built on (see run())


OUTFIT_SYSTEM_META = {
    "name": "Outfit System", "author": "D5 Mod Kit", "version": "1.0",
    "description": "Adds an 'Outfit' entry to the unit menu (Characters list) that switches a character between its outfits. "
                   "Each outfit keeps its own custom (precise) colours. Needed by outfit mods such as 'Girl Laharl Outfits'; "
                   "on its own it changes nothing."}


def outfit_system(work):
    """The Outfit System marker mod, written into this build's own folder (it used to be read from the installed mods).

    It is two small files (``mod.json`` and ``patches/outfits/system.json``, d5lib/outfits.py ``SYSTEM_FILE``); the
    installed copy carried the same content, so nothing is read from an installed pack."""
    folder=work/'dependencies'/outfits.SYSTEM_MOD_ID     # a mod's id is its folder name
    remove_created(folder)
    (folder/'patches'/'outfits').mkdir(parents=True,exist_ok=True)
    (folder/'mod.json').write_text(json.dumps(OUTFIT_SYSTEM_META,indent=2)+'\n',encoding='utf-8')
    (folder/'patches'/'outfits'/outfits.SYSTEM_FILE).write_text(json.dumps(
        {"enabled":True,"note":"marks this mod as the Outfit System (d5lib/outfits.py)"},indent=1),encoding='utf-8')
    record_created(folder)
    return folder


def source_data(ctx):
    """The verified DRPG input of this build (prepared source folder; ``ctx['source_root']`` names one explicitly)."""
    return _drpg_source.data(ctx.get('source_root'))


def source_fs(ctx):
    state=Path(ctx['state_root'])
    inst=object.__new__(modsys.Installer)
    inst.backup_dir=str(state/'backups')
    inst.index=json.loads((state/'backups.json').read_text())
    return gamefs.GameFS(str(ctx['game_path']), backup_resolver=inst.backup_resolver)


def patch_rows(mod, fs, fields):
    van, ed = outfits._char_tables(fs, mod)
    for cid, updates in fields.items():
        row = ed.find(int(cid))
        if row is None: raise ValueError(f'missing emitted row {cid}')
        for k,v in updates.items(): row.set(k,v)
    mod.save_patch('db','char.dat.json',dbpatch.diff_table(van,ed))


def plan(roster, ctx, leases=None):
    """Reserve the complete roster once, preserving installed replacement leases.

    Fail entries exceeding measured free low-row windows; never reuse a lease
    between independently emitted packs. This deliberately exposes finite space.

    leases: the DRPG v2 manifest (d5lib.importers.drpg_leases.load()).  When given it is authoritative and is
    READ, never recomputed (K0: "read the lease, don't recompute it"): every base takes its leased low row and its
    leased sprite (never sprite = row -- that would leave only 102 free low rows), and every costume takes its
    leased high class id with its leased art N as sprite_id = color_id (one declared look).
    """
    reference = bool(ctx.get('installed_reference'))
    key = tuple(str(ctx.get(k)) for k in ('installed_root','game_path','source_root','output_root'))+(str(reference),)
    if key in _PLAN: return _PLAN[key]
    fs = source_fs(ctx)
    try:
        char = database.load_table('char.dat', fs.read(DB+'char.dat'))
        data = source_data(ctx)
        # SOURCEPREP4-DRPG: the installed packs are read only on an explicit installed_reference; the lease manifest is the
        # authority for every id, so a machine with no installed pack plans the same roster.
        installed = Path(ctx['installed_root']) if reference else None; taken=set(); files=set(); replacements={}
        for d in (sorted(installed.iterdir()) if installed is not None else ()):
            if not d.is_dir() or not (d/'mod.json').exists(): continue
            mod=modsys.Mod(str(d)); _, ed=outfits._char_tables(fs,mod)
            p=mod.load_patch('db','char.dat.json') or {}
            touched={int(x['id']) for x in p.get('added',[]) if 'id' in x}
            touched|={int(char.rows[int(i)]['id']) for i in p.get('rows',{})}
            taken |= touched
            files|={int(p.name[3:8]) for p in d.rglob('anm*.lzs') if p.name[3:8].isdigit()}
            if d.name in {e.mod_folder for e in roster} or d.name=='Zed':
                pairs=outfits.load(mod); costume_ids={b for a,b in pairs}
                bases=[r for r in ed.rows if r['id'] in touched and r['id'] not in costume_ids]
                if bases:
                    b=bases[0]; replacements[d.name]=dict(row=b['id'],sprite=b['sprite_id'],
                        costumes=[dict(row=s,sprite=ed.find(s)['sprite_id']) for a,s in pairs])
        used=sprites.used_sprite_numbers(fs)|files
        for n in PENDING_ART_LEASES:
            used.update((n,n+1,n+2,n+10000,n+10001))
        pool=[]
        for cid in slots.unique_pool(fs):
            if cid in taken or {cid,cid+1,cid+2,cid+10000,cid+10001}&used: continue
            if all(abs(cid-j)>=3 for j in pool): pool.append(cid)
        # Sprite ids are measured separately. The new unique's class row owns its
        # keyed icon and portrait, so using the same free window avoids double use.
        allocated={}
        mbase, mcost = drpg_leases.index(leases) if leases is not None else ({}, {})
        for e in roster:
            c=e.source_ref['character']; looks=distinct_looks(c,e.source_ref['best_base_look'],data)
            if leases is not None:
                # The v2 manifest is the lease: read it, never recompute (a rebuild that reassigns ids breaks saves).
                b=mbase.get(e.id)
                if b is None: continue
                lease: dict = dict(row=b["class_id"], sprite=b["art"], costumes=[])
                for l in looks[1:]:
                    cl=mcost.get(f"drpg:{l['id']}")
                    if cl is None: raise ValueError(f'lease manifest has no costume {l["id"]} for {e.id}')
                    lease['costumes'].append(dict(row=cl['class_id'],sprite=cl['art'],
                                                  colour=cl['color_id'],look=l['id']))
                lease['looks']=looks
                lease['ordinal']=len(allocated)
                allocated[e.id]=lease
                continue
            existing=replacements.get(e.mod_folder) or (replacements.get('Zed') if c['base_id']==94 else None)
            needed=max(0,len(looks)-(1+len(existing['costumes']) if existing else 0))
            if len(pool)<needed: continue
            if existing:
                lease=dict(existing)
                lease['costumes']=list(existing['costumes'])
            else:
                if not pool: continue
                n=pool.pop(0);lease=dict(row=n,sprite=n,costumes=[]);needed-=1
            for _ in range(needed):
                n=pool.pop(0);lease['costumes'].append(dict(row=n,sprite=n))
            lease['looks']=looks
            lease['ordinal']=len(allocated)
            allocated[e.id]=lease
        from ._drpg_namespaces import reserve
        extra = [x for x in os.environ.get("D5_DRPG_EXTRA_CLAIMS", "").split(os.pathsep) if x]
        pinned = {eid: b["namespaces"] for eid, b in mbase.items() if b.get("namespaces")} if leases is not None else {}
        dirty = (leases.get('dirty_slots') or {}).get('slots', []) if leases is not None else []
        namespaces = reserve(allocated, fs, installed, extra_roots=extra, pinned=pinned, dirty_slots=dirty)
        for eid, lease in namespaces.items(): allocated[eid].update(lease)
        from ._drpg_namespaces import reserve_evilities
        for eid, remap in reserve_evilities(allocated,fs,installed,pinned={e:b['evilities'] for e,b in mbase.items() if b.get('evilities')}).items():
            allocated[eid]["evility_map"] = remap
        _PLAN[key]=allocated
        return allocated
    finally: fs.reset()


def source_assets(uid, data):
    """The unit's verified source files: every sheet must be a verified manifest row; icon and cut-in only when listed.

    Nothing else is consulted: an unlisted file in the folder (or an old derived art folder) never supplies a role.
    The explicit own cut-in folder (env D5_DRPG_OWN_CUTINS) can supply the cut-in the source lacks (DRPGCUTIN2)."""
    files={}
    for role,rel in data.unit_assets(uid).items():
        files[role]=dict(path=f'{_drpg_source.LABEL}/{rel}',sha256=data.sha256(rel),provenance=data.provenance(rel),rel=rel)
    if not all(k in files for k in _drpg_source.REQUIRED_ROLES):
        raise FileNotFoundError(f'No complete verified source sheets for DRPG unit {uid} (drpg/{_drpg_source.unit_files(uid)["front"]} '
                                'and its three siblings must be verified rows of the prepared source manifest)')
    if 'cutin' not in files and os.environ.get('D5_DRPG_OWN_CUTINS'):   # DRPGCUTIN2: the one made from the look's own illustration
        own=Path(os.environ['D5_DRPG_OWN_CUTINS'])/f'{uid}.png'
        if own.is_file(): files['cutin']=dict(path=str(own),sha256=sha256(own),provenance=OWN_CUTIN_PROVENANCE,own=str(own))
    provenance={v['provenance'] for v in files.values()}
    return dict(unit=uid, provenance=next(iter(provenance)) if len(provenance)==1 else 'mixed-original-and-derived',files=files)


def distinct_looks(c, best, data):
    """Deduplicate only identical sprite, face and cut-in assets; retain source ids."""
    looks=sorted(c['looks'],key=lambda l:(l['id']!=best,l['id']))
    seen={};out=[]
    for l in looks:
        try:
            a=source_assets(l['id'],data);sig=tuple(a['files'].get(k,{}).get('sha256') for k in ('front','back','wait_front','wait_back','icon','cutin'))
        except FileNotFoundError:
            sig=('missing',l['id']);a=None
        if sig in seen:
            out[seen[sig]]['equivalent_ids'].append(l['id']);continue
        seen[sig]=len(out)
        out.append(dict(l, assets=a, equivalent_ids=[]))
    return out


def stage_assets(looks, work, data):
    """Copy the verified bytes of every needed file into this build's own asset folder (read once, hash-checked)."""
    root=work/'assets'; mappings={'front':'Sprites/front','back':'Sprites/back','wait_front':'Sprites/wait_front','wait_back':'Sprites/wait_back','icon':'Icons','cutin':'Cut-Ins'}
    remove_created(root, strict=True)   # only the files an earlier run of this importer staged; nothing stale can be read
    uids={l['id'] for l in looks}
    from .. import monstermap
    if any(l.get('type')=='monster' for l in looks):
        # A monster look is paired with the vanilla monster template through that template's DRPG twin (monstermap): the
        # twin's atlas sheets are an input.  They are not in the user's JP client cache (the prepared source lacks them),
        # so the build refuses by name instead of failing deep inside the pairing.
        twin=monstermap.TWINS[MONSTER_TEMPLATE]
        if not data.sheets_complete(twin):
            raise _drpg_source.DrpgSourceError(
                f'{_drpg_source.LABEL}/{_drpg_source.unit_files(twin)["front"]} (and its three sibling sheets): no verified manifest '
                f'rows. A monster look needs the vanilla DRPG twin unit {twin} of monster template {MONSTER_TEMPLATE}; the prepared '
                'source does not hold it (it is not in the JP client cache RPGEXTRACT1 decoded). Supply the decoded sheets of the vanilla monster twins '
                'under Sprites/Standard in the folder given to tools/prep_source.py --drpg and run it again. See SOURCEPREP4-DRPG-REPORT.md.')
    uids|=set(monstermap.TWINS.values())
    for uid in sorted(uids):
        try: assets=source_assets(uid,data)
        except FileNotFoundError:
            if uid in {l['id'] for l in looks}: raise
            continue
        for k,v in assets['files'].items():
            p=root/'Characters'/mappings[k]/(f"{'back' if 'back' in k else 'front'}{uid}.png" if k in ('front','back','wait_front','wait_back') else f'{uid}.png')
            p.parent.mkdir(parents=True,exist_ok=True)
            if 'rel' in v:
                raw=data.read(v['rel'])                       # verified against the manifest SHA-256 in this very read
                p.write_bytes(raw)
            else:
                # An own cut-in is linked, not copied: drpgcutin.is_own() recognises it by the folder it really lives in
                # (the explicit own-cutins folder), which decides the portrait label ('illustration').
                raw=Path(v['own']).read_bytes()
                if hashlib.sha256(raw).hexdigest()!=v['sha256']: raise ValueError(f'{v["own"]} changed while the build ran')
                p.symlink_to(Path(v['own']).resolve())
    record_created(root)
    return str(root)


def apply_source_stats(mod, fs, base_id, options, notes):
    """STATORACLE1 flag (options drpg_stats='source', DECISION PENDING for Sean; default 'donor' = unchanged):
    every char row of the pack gets the RPG character's lv1 profile scaled onto the row's own (donor) stats,
    d5lib.statfidelity.drpg_map.  Needs options drpg_master_cache (the JSON tools/stat_oracle.py --drpg-cache
    writes from Disgaea Source masters/character).  Returns the stats fidelity label."""
    if options.get('drpg_stats', 'donor') != 'source':
        return 'donor'
    from .. import statfidelity as sf
    rpg = sf.drpg_rows(options['drpg_master_cache'])
    if base_id not in rpg:
        notes.append(f'Stats: donor (no RPG master row {base_id})')
        return 'donor'
    van, _ = outfits._char_tables(fs, mod)
    ctx = sf.drpg_context([r.to_dict() for r in van.rows], rpg)
    fields, maps = {}, []
    for row in (mod.load_patch('db', 'char.dat.json') or {}).get('added') or []:
        donor = [row['base_' + s] for s in sf.STATS]
        new = sf.drpg_map(rpg[base_id]['base'], donor, ctx['medians'])
        fields[row['id']] = {'base_' + s: v for s, v in zip(sf.STATS, new)}
        maps.append(dict(row=row['id'], donor=donor, base=new))
    patch_rows(mod, fs, fields)
    mod.meta.setdefault('source_import', {})['stat_mapping'] = dict(
        method='statfidelity.drpg_map v1 (STATORACLE1; decision pending)', source_id=base_id,
        medians={sf.STATS[int(k)]: v for k, v in ctx['medians'].items()}, rows=maps,
        labels='HP ATK DEF INT RES SPD scaled; SP HIT aptitudes donor')
    mod.save_meta()
    notes.append('Stats: RPG lv1 profile scaled onto the donor tier (HP ATK DEF INT RES SPD); SP, HIT, aptitudes donor')
    return 'scaled'


def run(request):
    work=request.parent;data=json.loads(request.read_text());e=data['entry'];ctx=data['ctx'];a=data['allocation']
    c=e['source_ref']['character'];looks=a['looks'];log=lambda s:print(s,flush=True)
    scratch=work/'tmp';scratch.mkdir(exist_ok=True)
    os.environ['TMPDIR']=str(scratch)
    tempfile.tempdir=str(scratch)
    data=source_data(ctx)
    root=stage_assets(looks,work,data);drpg.ROOTS[:]=[root]
    from .. import runtime
    cache=Path(ctx["output_root"])/"cache";cache.mkdir(exist_ok=True)
    sprites.CACHE_DIR=runtime.CACHE=str(cache)
    os.environ["ZIG_GLOBAL_CACHE_DIR"]=str(cache/"zig-global")
    os.environ["ZIG_LOCAL_CACHE_DIR"]=str(cache/"zig-local")
    from ._drpg_reference import configure
    reference_pins=configure(ctx['installed_root'] if ctx.get('installed_reference') else None)
    fs=source_fs(ctx)
    # TEXTHASH-DRPG: the reviewed overlays, titles and twin swaps hold their game text as hashes; this build's own pool (the
    # verified masters of the prepared folder and the pristine Disgaea 5 tables) resolves them.
    _drpg_text.use(_drpg_text.build_pool(ctx,fs))
    # Reuse the existing sample's row/evility helpers, not another implementation.
    spec=importlib.util.spec_from_file_location('drpg_sample',KIT/'tools/build_drpg_sample.py')
    sample=importlib.util.module_from_spec(spec);spec.loader.exec_module(sample)
    dest=work/'native-mods'/e['mod_folder'];dest.mkdir(parents=True,exist_ok=True)
    mod=modsys.Mod(str(dest))
    notes=['Art provenance per look: '+', '.join(str(l['id'])+'='+l['assets']['provenance'] for l in looks),
           'Specials backlog: template donor/adapted; no RPG specials are imported.',
           'Voice is the D5 template donor; no source cue-role mapping is claimed.']
    try:
        template=40
        mod.meta.update(name=c['name']+' (Disgaea RPG)',author='D5 project',version='0.1.0-private',category='characters',
                        description='One RPG base character; source looks are costumes. Offline hybrid conversion.',
                        credit='D5 Mod Kit (MIT); Cryswar / Overlord (The Unlicense), aura/regen reference design; Disgaea art © Nippon Ichi Software; DRPG master/name research credited in source references.',
                        source_import=dict(source=e['source_ref'],looks=looks,leased_ids=a,voice='D5 donor',specials='donor/adapted backlog',
                                           yield_source=donor_yield(NO_YIELD_FIELD_NOTE.format('DRPG'))))
        mod.save_meta()
        ids=iter([a['row']]+[x['row'] for x in a['costumes']]);sps=iter([a['sprite']]+[x['sprite'] for x in a['costumes']])
        slots.free_unique_ids=lambda *args,**kw:[next(ids)]
        outfits._free_sprite=lambda *args:next(sps)
        # Explicit deterministic help/quest leases, above the installed catalogue.
        outfits._free_help_id=lambda *args:a["help_id"]
        outfits._free_quest=lambda *args:(a["quest_id"], a["quest_slot"])
        monster_ids={l['id'] for l in looks if l['type']=='monster'}
        base_monster = looks[0]['type']=='monster'
        original_build=drpgmap.build
        monster_reports={}
        def build(fs_,uid,tmpl,N,**kw):
            if uid not in monster_ids: return original_build(fs_,uid,tmpl,N,**kw)
            from .. import monstermap
            mt=2010
            if os.path.exists(monstermap.role_path(uid)):
                roles=monstermap.load_roles(monstermap.role_path(uid));pairs=monstermap.pairs_from_roles(fs_,mt,uid,roles,roots=[root])
            else:
                roles=monstermap.auto_roles(fs_,mt,uid,roots=[root]);pairs=monstermap.pairs_from_roles(fs_,mt,uid,roles,roots=[root])
            out,rep=monstermap.build(fs_,uid,mt,N,pairs,roots=[root],roles=roles,log=log)
            monster_reports[str(uid)]=dict(template=mt,method='Kit role map or auto_roles',report=rep)
            return out,rep
        drpgmap.build=build
        skills=[]
        twins=(_drpg_text.load(Path(__file__).with_name('drpg-skill-twins.json'))['packs'].get(e['mod_folder']) or {})
        for cmd in c.get('commands',[]):
            sk=cmd.get('d5_id')
            if sk and cmd['verdict']!='omit':
                t=twins.get(str(sk))
                if t:
                    notes.append(f"Skill twin swap (motions): D5 {sk} {t['replaces']} (SP {t['replaces_sp']}) has no caster animation in this body's bank; adapted to D5 {t['twin']} {t['name']} (SP {t['sp']}), same element and area, motions present")
                    sk=t['twin']
                if sk not in [x[0] for x in skills]:skills.append((sk,1))
        res=outfits.create_drpg_character(fs,mod,template,template,looks[0]['id'],c['name'],
            'Disgaea RPG',skills if skills else None,('A visitor from Disgaea RPG.', 'D5 donor stats, skills adapted from RPG mapping.', 'DRPG specials remain donor/adapted.'),
            dict(title='A New Ally',client=c['name'],text='Meet a visitor from another Netherworld.'),roots=[root],log=log)
        vanilla=database.load_table('char.dat',fs.read(DB+'char.dat'))
        leaders=[];omitted=[]
        for ls in c.get('leader_skills',[]):
            ev=ls.get('evility') or ls.get('fallback_evility')
            if ev and ev.get('id') and ev['id'] not in leaders:leaders.append(ev['id'])
            else:omitted.append(dict(id=ls['rpg_id'],verdict=ls['verdict'],reason=ls['reason']))
        fields={f'evility{i}':leaders[i-1] if i<=len(leaders[:4]) else 0 for i in range(1,5)}
        fields['evility_count']=min(len(leaders),4)
        if len(leaders)>4: notes.append('Leader adaptation: only first four distinct mapped evilities fit the base row; omitted ids '+str(leaders[4:]))
        if not leaders:
            notes.append('No executable reviewed leader mapping: donor evility retained; '+json.dumps(omitted,ensure_ascii=False))
            fields={}
        if looks[0]['type']=='monster':
            donor=vanilla.find(2010)
            fields.update({k:donor[k] for k in outfits.HUMANOID_FIELDS+tuple(k for k in donor.keys() if k.startswith('mastery_'))})
        if c['base_id'] in (55,106,311):
            from .. import evility
            ss=copy.deepcopy(next(s for s in sample.SPECS if s['rpg']==c['base_id']))
            remap={int(k):int(v) for k,v in a['evility_map'].items()}
            def remap_self(node):
                if isinstance(node,dict):
                    return {k:(remap.get(v,v) if k=='id' and isinstance(v,int) else remap_self(v)) for k,v in node.items()}
                if isinstance(node,list): return [remap_self(v) for v in node]
                return node
            ss['evilities']={remap[k]:remap_self(v) for k,v in ss['evilities'].items()}
            notes.append('Collision-free sample evility leases (old -> new): '+str(remap))
            vanilla_skill=database.load_table('Skill.dat',fs.read(DB+'Skill.dat'))
            erows=[sample.evility_row(vanilla_skill.find(1235).to_dict(),eid,a['row'],c['name']+' leader skill',es['note']) for eid,es in ss['evilities'].items()]
            sample.add_skill_rows(mod,erows)
            evility.save(mod,dict(evilities={str(eid):{k:v for k,v in es.items() if k!='note'} for eid,es in ss['evilities'].items()}))
            leaders=sorted(ss['evilities']); fields.update({f'evility{i}':leaders[i-1] if i<=len(leaders) else 0 for i in range(1,5)});fields['evility_count']=len(leaders)
            notes.append('Preserved sample leader implementation: '+ss['leader'])
        if fields:sample.patch_char(mod,a['row'],vanilla,**fields)
        costumes=[]
        # The Kit hybrid builder needs a vanilla motion bank, not this mod's
        # newly leased sprite (which is not yet in GameFS).
        if looks[0]['type']=='monster':
            hybrid_builder=outfits._create_hybrid_files
            def hybrid_files(fs_,mod_,base_row,*args,**kw):
                donor_row=base_row.copy()
                donor_row.set('sprite_id',2010)
                donor_row.set('color_id',2010)
                return hybrid_builder(fs_,mod_,donor_row,*args,**kw)
            outfits._create_hybrid_files=hybrid_files
        for l in looks[1:]:
            cl=next((x for x in a['costumes'] if x.get('look')==l['id']), None)
            declared=dict(slot=cl['row'],colour=cl['colour']) if cl and cl.get('colour') else {}
            look_monster = l['type']=='monster'
            mixed = look_monster != base_monster
            # K4: a look that changes body kind gets ITS OWN body/companion/script set.  The kind decides the row and
            # the art set (outfits.create_drpg_outfit body=), never the character's; a monster look's motion/companion
            # donor is the vanilla monster 2010, a humanoid look's is the humanoid template 40.
            body=dict(body='monster' if look_monster else 'humanoid',
                      body_template=2010 if look_monster else 40) if mixed else {}
            r=outfits.create_drpg_outfit(fs,mod,a['row'],l['id'],l.get('en') or l.get('jp') or str(l['id']),template=template,roots=[root],log=log,
                hybrid=None if (not base_monster or mixed) else dict(template=40,sources={},keep=[]),**body,**declared)
            costumes.append(dict(unit=l['id'],declared=declared or None,**r))
            if l['type']=='monster':
                donor=vanilla.find(2010)
                patch_rows(mod,fs,{r['slot']:{k:donor[k] for k in outfits.HUMANOID_FIELDS+tuple(k for k in donor.keys() if k.startswith('mastery_'))}})
        from . import drpg_titles
        title_rows=drpg_titles.apply(dest,c['base_id'])    # SMALLFIX1: the character's own class title, not the group label
        from . import drpg_evilities
        own_ev=drpg_evilities.apply(dest,c['base_id'])     # DRPGEVIL1: the character's own source evilities, donors kept for the rest
        if own_ev:
            mod.meta.update(json.loads((dest/'mod.json').read_text()))
            notes.append(f"Own source evilities (DRPG leaderskill, overlay): {own_ev['own']}; char links {own_ev['links']}")
        from . import drpg_skills
        sk_vanilla=drpg_skills.vanilla_rows(fs)
        own_sk=drpg_skills.apply(dest,c['base_id'],vanilla=sk_vanilla)        # DRPGSKILL1: the character's own source skills, donor links kept for the rest
        if own_sk:
            mod.meta.update(json.loads((dest/'mod.json').read_text()))
            notes.append(f"Own source skills (DRPG command masters, overlay): {own_sk['own']}; learn list {own_sk['learn']}")
        from ._drpg_monsters import support
        monster_events=[]
        if looks[0]['type']=='monster':
            monster_events+=support(fs,mod,a['sprite'])
        for l,r in zip(looks[1:],costumes):
            # K4: only a MONSTER look needs the monster companion + normal-attack roots; a humanoid costume of a
            # monster character is a humanoid body (its own-animation copy is already written) and gets none.
            if l['type']=='monster':
                monster_events+=support(fs,mod,r['sprite'])
        if monster_events:
            notes.append('Monster normal/skip attacks and companion filter reuse Kit newclasses helpers; donor/adapted 2010.')
        notes.extend('Leader mapping omitted: '+json.dumps(x,ensure_ascii=False) for x in omitted)
        if monster_reports: notes.append('Monster motion pairing is automatic/adapted; native weapon behavior untested.')
        # K2C (DECISIONS 2026-11-06): a look whose source has no cut-in keeps the base's portrait.  That is a labelled
        # donor in the pack (outfits.json "portraits") and here, never a silent approximation.
        declared_portraits=outfits.load_portraits(mod)
        portrait_labels = {str(c0['unit']): declared_portraits[c0['slot']]
                           for c0 in costumes if c0.get('slot') in declared_portraits}
        if portrait_labels:
            donors = sorted(k for k, v in portrait_labels.items() if v not in ('own', 'illustration'))
            mod.meta['source_import']['portraits'] = portrait_labels
            mod.save_meta()
            if donors:
                notes.append('Portrait: donor (source has no cut-in) for look(s) ' + ', '.join(donors))
        illus=[l['id'] for l in looks if l['assets']['files'].get('cutin',{}).get('provenance')==OWN_CUTIN_PROVENANCE]
        if illus:                   # DRPGCUTIN2: labelled in the pack and here, never a silent substitute
            mod.meta['source_import']['cutin_from_illustration']={str(i):OWN_CUTIN_LABEL for i in illus}
            names={l['id']:l.get('en') or str(l['id']) for l in looks}
            mod.meta['description']=mod.meta['description']+' Cut-in for '+', '.join(f'{names[i]} ({i})' for i in illus)+': '+OWN_CUTIN_LABEL+'.'
            mod.save_meta()
            notes.append('Cut-in: '+OWN_CUTIN_LABEL+' (look(s) '+', '.join(map(str,illus))+')')
        if reference_pins:
            mod.meta['source_import']['pose_reference']=list(reference_pins.values())
            mod.save_meta()
            notes.append('Silhouette fallback used the existing Kit learned pose cache, pinned separately: '+str(list(reference_pins.values())))
        stats_label=apply_source_stats(mod,fs,c['base_id'],ctx.get('options') or {},notes)
        # Full Kit finalize (in memory) exercises rows, hooks, portraits and scripts.
        system=outfit_system(work)
        mods=[modsys.Mod(str(system)),mod]
        if modsys.missing_requirements(mods): raise ValueError('Missing Kit dependency')
        finalized=modsys.build(fs,mods,log=log)
        skipped=list(getattr(finalized,'skipped_features',[]))
        if skipped: notes.append('Skipped Kit features: '+str(skipped))
        char=database.load_table('char.dat',finalized.get(DB+'char.dat'))
        row=char.find(a['row']);readback=bool(row and row['name_EN']==c['name'])
        # K2 art contract: every id a declared costume claims must resolve to art this build wrote.
        from . import drpg_art
        icon_cells=getattr(finalized,'_icon_cells',{})
        art_contracts=[];art_problems=[]
        # D5_K2_ART_DROP=<substring>: negative control only -- hide one contract input and the gate must fail.
        _drop=os.environ.get('D5_K2_ART_DROP','')
        def _get(vp):
            if _drop and _drop.lower() in vp.lower(): raise KeyError(vp)
            return finalized.get(vp)
        for l,r in zip(looks[1:],costumes):
            cl=next((x for x in a['costumes'] if x.get('look')==l['id']),None)
            if cl is None: continue
            ok,probs,table=drpg_art.contract(dict(class_id=r['slot'],art=r['sprite']),_get,
                icon_cells=icon_cells,row=char.find(r['slot']))
            art_contracts.append(dict(look=l['id'],ok=ok,problems=probs,**table))
            art_problems+= [f"look {l['id']}: {p}" for p in probs]
        art_ok=not art_problems
        if art_problems: notes.append('Art contract: '+drpg_art.summary(art_problems))
        from .. import script, scriptpatch
        events={e.id for e in script.ScriptFile.from_bytes(finalized.get(scriptpatch.SCRIPT)).events}
        monster_scripts=all(eid in events for eid in monster_events)
        from .. import anm
        counts=[]
        for p in sorted((dest/'files').rglob('anm*.lzs')):
            z=anm.load(str(p));counts.append(dict(path=str(p.relative_to(dest)),palettes=len(z.palettes),textures=len(z.textures),headers=len(z.palettes)+len(z.textures)))
        old=Path(ctx['installed_root'])/('Zed' if c['base_id']==94 else e['mod_folder']) if ctx.get('installed_reference') else None
        from . import _drpg_roster
        shapes={rel:tuple(v) for rel,v in (_drpg_roster.bank_shapes().get(e['mod_folder']) or {}).items()}
        wheel,why=wheel_gate(dest,old,reference=shapes)
        # A renamed Zed writes matching bank13000 so shared comparison still works.
        title_ok,title_why=drpg_titles.gate(dest,c['base_id'])
        if title_why: notes.append('Class title: '+title_why)
        evil_ok,evil_why=drpg_evilities.gate(dest,c['base_id'])
        notes.append('Own evilities: '+evil_why)
        skill_ok,skill_why=drpg_skills.gate(dest,c['base_id'],vanilla=sk_vanilla)
        notes.append('Own skills: '+skill_why)
        receipt=dict(ok=readback and wheel and monster_scripts and art_ok and title_ok and evil_ok and skill_ok and not skipped,gates=dict(own_skills=skill_ok,kit_finalize=not skipped,character_readback=readback,replacement_wheel=wheel,monster_attack_scripts=monster_scripts,art_contract=art_ok,class_title=title_ok,own_evilities=evil_ok),
            features={k:(stats_label if k=='stats' else 'donor' if k in ('voice','specials') else 'adapted' if k in ('skills','evilities','attack','hurt','carried') else 'own') for k in ('stand','walk','attack','hurt','carried','face','cutin','stats','skills','evilities','voice','specials','recruit')},
            notes=notes+([why] if why else []),character=res,costumes=costumes,assets=looks,anm_counts=counts,art_contracts=art_contracts,
            monster_reports=monster_reports,finalized_outputs=len(finalized.outputs),leased_ids=a)
        receipt['features']['ranks']='n/a'
        receipt['features']['face']='own' if all('icon' in l['assets']['files'] for l in looks) else 'donor'
        receipt['features']['cutin']='own' if all('cutin' in l['assets']['files'] for l in looks) else 'donor'
        if illus and receipt['features']['cutin']=='own': receipt['features']['cutin']='own (illustration)'
        if illus: receipt['cutin_from_illustration']=mod.meta['source_import']['cutin_from_illustration']
        receipt['features']['portrait']='donor' if any(v not in ('own','illustration') for v in portrait_labels.values()) else 'own'
        receipt['portraits']=portrait_labels
        receipt['own_evilities']=own_ev
        receipt['own_skills']=own_sk
        (work/'receipt.json').write_text(json.dumps(receipt,indent=1,ensure_ascii=False,default=str)+'\n')
        (dest/'CORERPG1-receipt.json').write_text(json.dumps(receipt,indent=1,ensure_ascii=False,default=str)+'\n')
        return 0 if receipt['ok'] else 1
    finally:fs.reset()


if __name__=='__main__':
    try:sys.exit(run(Path(sys.argv[1])))
    except Exception:
        traceback.print_exc();sys.exit(1)
