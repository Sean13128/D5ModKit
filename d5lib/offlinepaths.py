"""Read-only filesystem checks for game-derived offline outputs.

Path.resolve() follows symlinks but need not canonicalize case on a
case-insensitive filesystem. Existing ancestors must also be compared by identity.
These checks do not create paths, reserve names, or replace exclusive creation.
"""
import os
from pathlib import Path
from unicodedata import normalize


def contains(root, path):
    """Whether path is root or beneath it, including existing filesystem aliases."""
    root, path = Path(root).resolve(), Path(path).resolve()
    if path.is_relative_to(root):
        return True
    # Walking the candidate's ancestors handles new descendants beneath a case
    # alias of an existing protected root without folding unrelated Linux names.
    try:
        root_stat = root.stat()
    except FileNotFoundError:
        return False
    for candidate in (path, *path.parents):
        try:
            candidate_stat = candidate.stat()
        except FileNotFoundError:
            continue
        if (candidate_stat.st_dev, candidate_stat.st_ino) == (root_stat.st_dev, root_stat.st_ino):
            return True
    return False


def overlaps(left, right):
    """Whether either resolved path contains the other, by name or identity."""
    return contains(left, right) or contains(right, left)


def separate_outputs(*destinations):
    """Require independent write destinations, including future case aliases.

    Unlike protected-input containment, this is a conservative portable policy:
    NFC-normalized/casefolded component ancestry is forbidden on every volume.
    No files are created to discover filesystem behavior. Resolving first also
    catches dangling cache links into differently cased future output paths.
    """
    resolved = [Path(path).resolve() for path in destinations]
    for index, left in enumerate(resolved):
        for right in resolved[index + 1:]:
            a = tuple(normalize('NFC', normalize('NFC', part).casefold()) for part in left.parts)
            b = tuple(normalize('NFC', normalize('NFC', part).casefold()) for part in right.parts)
            if overlaps(left, right) or a[:len(b)] == b or b[:len(a)] == a:
                raise ValueError('Offline output destinations must be separate: ' + str(left) + ' / ' + str(right))


def offline_output(path, protected=()):
    """Return a resolved offline destination, or reject protected-path overlap.

    Call before reading game data or creating output/cache directories. Explicit
    roots protect repository, games, state, mods and input artifacts. The Steam
    marker additionally protects other game installs where no game was supplied.
    """
    output = Path(path).resolve()
    parts = tuple(part.casefold() for part in output.parts)
    if any(pair == ('steamapps', 'common') for pair in zip(parts, parts[1:])):
        raise ValueError('Offline output must stay outside Steam game installations')
    for root in protected:
        if root is not None and overlaps(output, root):
            raise ValueError('Offline output overlaps protected input: ' + str(root))
    return output


def require_output_cache(cache, output, protected=()):
    """Admit an actual caller-configured cache; never redirect shared globals."""
    try:
        actual = offline_output(cache, protected)
        separate_outputs(output, actual)
        expected = Path(str(output) + '.cache').resolve()
        if actual != expected:
            raise ValueError('actual cache must resolve to ' + str(expected))
    except ValueError as exc:
        raise ValueError('Configure private per-output caches or use the CLI: ' + str(exc)) from exc


INSTALLED_MODS_DEFAULT = '/Volumes/Data/Projects/D5/Local/Installed D5ModKit/mods'


def installed_mods_root():
    """The mods folder importers compare against and read installed references from.

    D5_INSTALLED_MODS overrides the live kit (e.g. the PLAYTEST-RESET holding folder)."""
    return Path(os.environ.get('D5_INSTALLED_MODS', INSTALLED_MODS_DEFAULT))
