"""Kit monster companion and normal-attack support for one unique look.

The generic builder already supplies the design: monster_companion and
add_class_scripts. Retain only the single unique sprite's three events; a unique
has no ten-rank family, and neighboring event ids belong to other leases.
"""
from .. import anm, newclasses, script, scriptpatch, sprites


def support(fs, mod, sprite, template=2010):
    path = f'Anime/ANM_HI_JP.dat/anm{sprite:05d}.lzs'
    bank = anm.load(mod.read_file(path))
    # The Kit helper falls back to a full copy when the companion is absent;
    # that is unsafe for this install-ready path, so require the real donor.
    anm.parse(fs.read(sprites.sprite_vpath(fs, template + 1, "EN")))
    companion = newclasses.monster_companion(fs, bank, template, sprite)
    mod.write_file(f'Anime/ANM_HI_JP.dat/anm{sprite + 1:05d}.lzs', companion.to_bytes())
    raw = fs.read(scriptpatch.SCRIPT)
    vanilla = script.ScriptFile.from_bytes(raw)
    edited = script.ScriptFile.from_bytes(raw)
    newclasses.add_class_scripts(edited, vanilla, {
        sprite: dict(template=template, kind='monster', sprite_family=sprite)})
    added = scriptpatch.diff(vanilla, edited).get('events', {})
    required = {str(p + sprite) for p in newclasses.MONSTER_SCRIPTS}
    chosen = {k: v for k, v in added.items() if k in required}
    if set(chosen) != required:
        raise ValueError(f'Monster donor {template} lacks normal/skip attack scripts for sprite {sprite}')
    patch = mod.load_patch('script', 'script.json') or {}
    patch.setdefault('events', {}).update(chosen)
    mod.save_patch('script', 'script.json', patch)
    return sorted(int(k) for k in chosen)
