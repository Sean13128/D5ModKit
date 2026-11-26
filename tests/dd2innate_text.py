"""The DD2 source strings the innate-evility unit tests resolve their ``@text`` references against.

TEXTHASH-D1C-DD2: ``dd2-innate-evilities.json`` stores game names (and the two rows whose text is the
source text) as SHA-256 references.  The build reads them from the prepared DD2 source; these unit
tests exercise the same reviewed rows without a game dump, so they name the handful of strings those
rows use.  A test that resolves a row not listed here fails with the same clear refusal the build
gives, which is the honest answer: that row needs the real source.
"""
from d5lib import textrefs
from d5lib.importers import _dd2_innates

STRINGS = (
    'Acceleration Mascot',
    'Basic Principles',
    'Brave Battle Princess',
    'Cannot be lifted.',
    'God of Destruction',
    'Healing Barrier',
    'Heavy Stance',
    'Rapid Movement',
    'The Artifact',
    'Water Dominance',
)
POOL = textrefs.TextPool(STRINGS, label='the DD2 strings the unit tests name')


def pick(folder, data=None):
    """One reviewed innate row with its references resolved from :data:`POOL`."""
    return _dd2_innates.reviewed_pick(folder, data, POOL.get)
