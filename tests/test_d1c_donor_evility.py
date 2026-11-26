"""D1CEVIL1: the donor-evility table covers every in-scope D1C pack with a vanilla id and the importer applies it."""
import json
from pathlib import Path
from d5lib import textrefs
from d5lib.importers import d1c

ROOT = Path(__file__).resolve().parents[1]
TABLE = json.loads(d1c.DONOR_EVILITIES.read_text())
# TEXTHASH-D1C-DD2: the shipped table stores the D5 donor/evility text as SHA-256 references; the
# build reads it from the Disgaea 5 tables.  This test names the one row it applies so it needs no game.
PRIERE = textrefs.TextPool(['Overlord Priere', 'Bundle Attack',
                            'Increase damage dealt by panels devoid of units in the attack range x %d\uff05.'],
                           label='the D5 strings the unit test names')


def test_table_shape():
    assert sum(1 for v in TABLE['mods'].values() if not v.get('scope')) == 45     # the tracker roster (D1CEVIL1)
    assert sum(1 for v in TABLE['mods'].values() if v.get('scope')) == 14         # EVILFX3: installed folders outside it
    for mod, r in TABLE['mods'].items():
        assert r['rung'] in (1, 2, 3) and r['confidence'] in ('high', 'medium', 'low') and r['reason'], mod
        assert 0 < r['evility_id'] < 7000, mod            # a vanilla D5 Skill.dat id, no new rows


def test_apply(tmp_path):
    (tmp_path / 'patches/db').mkdir(parents=True)
    rows = [dict(id=i, evility1=0, evility2=0, evility3=0, evility4=0, evility_count=0) for i in (1, 2)]
    (tmp_path / 'patches/db/char.dat.json').write_text(json.dumps(dict(table='char.dat', added=rows)))
    (tmp_path / 'mod.json').write_text(json.dumps(dict(source_import={})))
    d1c.apply_donor_evility(tmp_path, 'D1C_Unique_3000', text=PRIERE.get)
    out = json.loads((tmp_path / 'patches/db/char.dat.json').read_text())['added']
    assert [(r['evility1'], r['evility_count']) for r in out] == [(6120, 1)] * 2
    si = json.loads((tmp_path / 'mod.json').read_text())['source_import']
    assert si['signature_evility'] == 'donor' and si['signature_evility_donor']['donor_name'] == 'Overlord Priere'
