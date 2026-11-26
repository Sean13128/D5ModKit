"""The DRPG learned pose reference: a pinned kit file, never an installed copy (SOURCEPREP4-DRPG, POSEREF1 note).

``d5lib/data/drpg_ref_humanoid.pickle`` (101 reference silhouettes of one labelled humanoid, 18 MB) is *not in Git*
(``.gitignore`` since the upstream 1.1 commit); upstream release packages carry it, and its upstream generator
``_research/drpg_make_ref.py`` is unpublished.  ``tools/drpg_make_ref.py`` (POSEREF1) rebuilds it byte for byte from
the labelled sheet ``SpriteSheet/Girl_Laharl/Girl_Laharl_Swimsuit_SS.png`` that the same release zip carries.
It is rendering reference data, not evidence of a source game's roster or art.

A pickle runs code when it is loaded, so the file is used only when its SHA-256 equals the pin recorded in
``drpg-pose-reference.json`` (the bytes the verified builds used).  It is looked up in the kit's own ``d5lib/data``
folder and nowhere else; the installed kit's copy is read only on an explicit ``installed_reference``.
"""
import hashlib
import json
from pathlib import Path
from .. import drpg

PIN = Path(__file__).with_name('drpg-pose-reference.json')
LABEL = 'd5lib/data/drpg_ref_humanoid.pickle'


class PoseReferenceError(FileNotFoundError):
    pass


def pin():
    return json.loads(PIN.read_text(encoding='utf-8'))


def configure(installed_mods=None):
    """Make ``drpg.load_reference`` read only the pinned file; return the pins of the file actually used.

    ``installed_mods`` (an explicit ``installed_reference`` only) adds the installed kit's copy as a fallback."""
    expected = pin()
    original_load = drpg.load_reference
    choices = [Path(drpg.REF_PATH)]
    if installed_mods:
        choices.append(Path(installed_mods).parent / 'd5lib/data/drpg_ref_humanoid.pickle')
    used = {}

    def load(path=None):
        chosen = next((p for p in ([Path(path)] if path is not None else choices) if p.is_file()), None)
        if chosen is None:
            raise PoseReferenceError(
                f'DRPG learned pose reference missing: put the upstream release file at {drpg.REF_PATH} '
                f'(SHA-256 {expected["sha256"]}, {expected["size"]} bytes), or rebuild it from the release zip\'s labelled sheet: '
                f'python tools/drpg_make_ref.py --release-zip <D5ModKit zip> --out {drpg.REF_PATH}. It is not in Git.')
        raw = chosen.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected['sha256']:
            raise PoseReferenceError(
                f'{chosen} (SHA-256 {digest}) is not the pinned DRPG pose reference ({expected["sha256"]}); '
                'refusing to unpickle it.')
        used[LABEL] = dict(path=LABEL, sha256=digest, provenance='Kit learned pose-reference cache')
        import io, pickle
        return pickle.load(io.BytesIO(raw))

    drpg.load_reference = load
    return used
