#!/usr/bin/env python3
"""Turn the Disgaea 4 game text still stored literally in the kit's tracked data into build-time references (TEXTHASH-D4).

Maintainer tool, not used at build time.  The nine ``d5lib/importers/d4-*.json`` rule files were already written as
references by ``tools/build_d4_rules.py`` (SOURCEPREP4-D4).  This tool covers the files that lane did not touch:

    d5lib/importers/d4-leases.json   (name, installed_name)
    d5lib/importers/d4-scope.json    (name)
    d5lib/sourcemaps/d4.json         (d4_name, d4_desc, desc, works_like_name, copy_of_name, d5_name, name, personalities)
    evility/carriers-content.json, carriers2-content.json, carriers2-ranking.json   (d4_name, desc, name, text)

A string in a name/desc/title/text field becomes the form ``_d4_source.TextPool.ref`` gives it: ``{"@text": sha256}``,
``{"@template": sha256, "args": [...]}``, ``{"@prefix": ..., "@text": ...}`` or ``{"@segments": [...]}``; a sentence no
game table holds (the kit's own adaptation wording) becomes ``{"@authored": text}``.  Every form is checked to resolve
back to exactly the original string.  The pool is the user's prepared D4 folder plus the Disgaea 5 tables, so the tool
needs the same inputs a build does.  Files already written as references are left alone, so it is idempotent.

    D5_SOURCE_DIR=<prepared folder> <kit venv python> tools/hash_d4_text.py --game-path <D5> --state <D5 state> [--check]

``hash_document(doc, pool)`` is the same transformation for a generator that writes one of these files
(``tools/build_d4_leases.py``, ``tools/build_d4_scope.py``, ``tools/d4npc1_leases.py``).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

FILES = (
    'd5lib/importers/d4-leases.json',
    'd5lib/importers/d4-scope.json',
    'd5lib/sourcemaps/d4.json',
    'evility/carriers-content.json',
    'evility/carriers2-content.json',
    'evility/carriers2-ranking.json',
    # written by tools/build_d4_rules.py (SOURCEPREP4-D4); re-checked here for quoted game text kept as kit wording
    'd5lib/importers/d4-allocation.json',
    'd5lib/importers/d4-mapping.json',
    'd5lib/importers/d4-extension-rows.json',
    'd5lib/importers/d4-extension-rows-cast.json',
    'd5lib/importers/d4-specials.json',
    'd5lib/importers/d4-evility-overlay.json',
    'd5lib/importers/d4-evility-additions.json',
    # the MAGICHANGE lane's content (D4 attack names/descriptions, character names) and its report
    'magichange/magichange-content.json',
    'magichange/rows.json',
)
# keys that hold game text in a file beyond the generic name/desc/title/text fields
FILE_KEYS = {
    'magichange/magichange-content.json': {'character', 'single', 'pair', 'dual'},
    'magichange/rows.json': {'character'},
}
TEXT_KEY = re.compile(r'(^|_)(name|desc|title|text)$')
REF_FORMS = {'@text', '@template', '@segments', '@authored', '@skeleton'}
# the sourcemap's `personalities` map (D4 personality names per class family): a list of names, not name fields
LIST_KEYS = {'personalities'}
# kit prose is converted only where it quotes a description (a template or a game string this long), never a bare name
PROSE_MIN = 25


def _is_ref(value):
    return isinstance(value, dict) and bool(REF_FORMS & set(value))


def _partial_template(pool, value):
    """A D4 template rendered with only its first numbers filled in (``... by 10%, ... by %d%.``)."""
    cache = pool.__dict__.get('_partial_patterns')
    if cache is None:
        cache = []
        for digest, text in pool._templates.items():
            if '%d' not in text:
                continue
            pieces = re.split(r'(%d|%%)', text)
            pattern = ''.join('(-?\\d+|%d)' if p == '%d' else '[%\uff05]' if p == '%%' else re.escape(p)
                              for p in pieces)
            anchor = max((p for p in pieces if p not in ('%d', '%%')), key=len, default='')
            cache.append((digest, text, re.compile('^' + pattern + '$'), anchor))
        pool._partial_patterns = cache
    for digest, text, pattern, anchor in cache:
        if anchor and anchor not in value:
            continue
        match = pattern.match(value)
        if not match:
            continue
        args = []
        for group in match.groups():
            if group == '%d':
                break
            args.append(int(group))
        doc = {'@template': digest, 'args': args}
        if '%%' in text:
            doc['percent'] = next((c for c in pool.PERCENTS if c in value), '%')
        if pool.resolve(doc) == value:
            return doc
    return None


def _affixed(pool, value):
    """A game name with a word or two of kit wording on either side (``Warrior line``)."""
    texts = set(pool._text.values())
    for cut in range(len(value) - 1, 2, -1):
        head, tail = value[:cut], value[cut:]
        if head in texts and head.strip() and tail.startswith((' ', ':', '-', '(')):
            doc = {'@segments': [{'@text': pool_sha(head)}, tail]}
            if pool.resolve(doc) == value:
                return doc
        head, tail = value[:len(value) - cut], value[len(value) - cut:]
        if tail in texts and head.endswith((' ', ':', '-', ')')):
            doc = {'@segments': [head, {'@text': pool_sha(tail)}]}
            if pool.resolve(doc) == value:
                return doc
    return None


def pool_sha(value):
    from d5lib.importers import _d4_source
    return _d4_source.text_sha(value)


def make_ref(pool, value):
    """The reference for one text-field string; refuses to return a form that does not resolve to ``value``."""
    ref = pool.ref(value)
    if isinstance(ref, dict) and set(ref) == {'@authored'}:
        ref = _partial_template(pool, value) or _affixed(pool, value) or ref
    if pool.resolve(ref) != value:                                     # pragma: no cover - guarded by the builders
        raise ValueError(f'reference does not resolve back to its text: {value!r}')
    return ref


def _template_spans(pool, value):
    """(start, end, reference) of every game template rendered inside ``value`` (prose quoting a description with
    its numbers filled in, or a quote that drops the final full stop), longest first, non-overlapping."""
    cache = getattr(pool, '_embed_patterns', None)
    if cache is None:
        cache = []
        for digest, text in pool._templates.items():
            if len(text) < PROSE_MIN:
                continue
            for trim in ((0, 1) if text.endswith('.') else (0,)):
                body = text[:len(text) - trim]
                pieces = re.split(r'(%d|%%)', body)
                pattern = ''.join('(-?\\d+)' if p == '%d' else '[%\uff05]' if p == '%%' else re.escape(p)
                                  for p in pieces)
                anchor = max((p for p in pieces if p not in ('%d', '%%')), key=len, default='')
                cache.append((len(text), digest, trim, '%%' in text, re.compile(pattern), anchor))
        cache.sort(key=lambda c: -c[0])
        pool._embed_patterns = cache
    found = []
    for _length, digest, trim, has_pct, pattern, anchor in cache:
        if anchor and anchor not in value:                  # cheap literal prefilter before the regex
            continue
        for m in pattern.finditer(value):
            start, end = m.span()
            if start and (value[start - 1].isalnum()):
                continue
            if end < len(value) and value[end].isalnum():
                continue
            doc = {'@template': digest, 'args': [int(n) for n in m.groups()]}
            if has_pct:
                span = value[start:end]
                doc['percent'] = next((c for c in pool.PERCENTS if c in span), '%')
            if trim:
                doc['trim'] = trim
            if pool.resolve(doc) == value[start:end]:
                found.append((start, end, doc))
    found.sort(key=lambda f: (-(f[1] - f[0]), f[0]))
    chosen = []
    for start, end, doc in found:
        if all(end <= a or start >= b for a, b, _ in chosen):
            chosen.append((start, end, doc))
    return sorted(chosen)


def embedded(pool, value):
    memo = pool.__dict__.setdefault('_embedded_memo', {})
    if value not in memo:
        memo[value] = _embedded(pool, value)
    return memo[value]


def _embedded(pool, value):
    """``value`` (kit prose) as kit-written pieces and references, when it quotes game text: a long exact game
    string, or a template with its numbers rendered.  None when it quotes nothing."""
    if len(value) < PROSE_MIN:
        return None
    spans = _template_spans(pool, value)
    longs = pool.__dict__.get('_prose_longs')
    if longs is None:
        longs = pool._prose_longs = {t for t in pool._text.values() if len(t) >= PROSE_MIN}
        pool._prose_lengths = sorted({len(t) for t in longs}, reverse=True)
    lengths = pool._prose_lengths
    pieces, pos, hits = [], 0, len(spans)
    def add_text(text):
        nonlocal hits
        if not text:
            return
        parts, i, buf = [], 0, ''
        while i < len(text):
            for length in lengths:
                if (length <= len(text) - i and text[i:i + length] in longs
                        and pool._boundary(text, i, i + length)):
                    if buf:
                        parts.append(buf)
                        buf = ''
                    parts.append({'@text': pool_sha(text[i:i + length])})
                    hits += 1
                    i += length
                    break
            else:
                buf += text[i]
                i += 1
        if buf:
            parts.append(buf)
        for part in parts:
            if isinstance(part, str) and pieces and isinstance(pieces[-1], str):
                pieces[-1] += part
            else:
                pieces.append(part)
    for start, end, doc in spans:
        add_text(value[pos:start])
        pieces.append(doc)
        pos = end
    add_text(value[pos:])
    if not hits:
        return None
    doc = pieces[0] if len(pieces) == 1 and isinstance(pieces[0], dict) else {'@segments': pieces}
    return doc if pool.resolve(doc) == value else None


def upgrade_doc(doc, pool, report=None):
    """A document that already uses references, with every kit-written (``@authored``) sentence and every plain
    prose string re-checked for quoted game text; what quotes game text becomes ``@segments``/``@template``."""
    if isinstance(doc, dict):
        if set(doc) == {'@authored'}:
            ref = _partial_template(pool, doc['@authored']) or embedded(pool, doc['@authored'])
            ref = ref or (pool._templated(doc['@authored']) if pool.ref(doc['@authored']) != doc else None)
            if ref and pool.resolve(ref) == doc['@authored']:
                if report is not None:
                    report['@authored->ref'] = report.get('@authored->ref', 0) + 1
                return ref
            return doc
        if _is_ref(doc):
            return doc
        return {k: upgrade_doc(v, pool, report) for k, v in doc.items()}
    if isinstance(doc, list):
        return [upgrade_doc(v, pool, report) for v in doc]
    if isinstance(doc, str):
        ref = embedded(pool, doc)
        if ref:
            if report is not None:
                report['prose->ref'] = report.get('prose->ref', 0) + 1
            return ref
    return doc


def hash_document(doc, pool, report=None, key='', extra=frozenset()):
    """``doc`` with every text-field string replaced by its reference (new structure; ``doc`` is not changed).

    Existing references and plain prose are re-checked for quoted game text (``upgrade_doc``)."""
    if _is_ref(doc):
        return upgrade_doc(doc, pool, report)
    if isinstance(doc, dict):
        out = {}
        for k, v in doc.items():
            if k in LIST_KEYS and isinstance(v, dict):
                out[k] = {sid: [make_ref(pool, n) if isinstance(n, str) and n else n for n in names]
                          if isinstance(names, list) else names for sid, names in v.items()}
            else:
                out[k] = hash_document(v, pool, report, k, extra)
        return out
    if isinstance(doc, list):
        return [hash_document(v, pool, report, key, extra) for v in doc]
    if isinstance(doc, str) and doc and (TEXT_KEY.search(key) or key in extra):
        ref = upgrade_doc(make_ref(pool, doc), pool)
        if report is not None:
            form = next(k for k in ref if k.startswith('@'))
            report[(key, form)] = report.get((key, form), 0) + 1
        return ref
    if isinstance(doc, str):
        return upgrade_doc(doc, pool, report)
    return doc


def _count(doc, forms):
    if _is_ref(doc):
        for form in REF_FORMS:
            if form in doc:
                forms[form] = forms.get(form, 0) + 1
        return
    if isinstance(doc, dict):
        for v in doc.values():
            _count(v, forms)
    elif isinstance(doc, list):
        for v in doc:
            _count(v, forms)


def _swap_text(text, original, hashed):
    """Rewrite a hand-formatted file in place: replace each changed string literal by its reference, keeping every
    other byte (the file is not re-indented).  Refuses when a literal also occurs where nothing changed."""
    changes = {}

    def pairs(a, b):
        if isinstance(a, dict) and not _is_ref(a):
            for k in a:
                yield from pairs(a[k], b[k])
        elif isinstance(a, list):
            for x, y in zip(a, b):
                yield from pairs(x, y)
        elif a != b:
            yield a, b
    counts = {}
    for old, new in pairs(original, hashed):
        if changes.setdefault(old, new) != new:
            raise SystemExit(f'the same text {old!r} would get two different references')
        counts[old] = counts.get(old, 0) + 1
    for old, new in changes.items():
        needle = json.dumps(old, ensure_ascii=False)
        if text.count(needle) != counts[old]:
            raise SystemExit(f'cannot place {old!r} in the file text ({text.count(needle)} occurrences, '
                             f'{counts[old]} changes)')
        text = text.replace(needle, json.dumps(new, ensure_ascii=False))
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--game-path', required=True, help='the Disgaea 5 folder (its tables are part of the pool)')
    ap.add_argument('--state', required=True, help='the kit state folder holding backups.json for that game')
    ap.add_argument('--check', action='store_true', help='write nothing; exit 1 if a file still holds literal text')
    ap.add_argument('files', nargs='*', help='default: every file this tool owns')
    args = ap.parse_args(argv)

    from d5lib.importers import _d4_source, dd2
    pool = _d4_source.text_pool(_d4_source.data_dir(),
                                dd2.original_fs({'game_path': args.game_path, 'state_root': args.state}))
    stale = 0
    for name in args.files or FILES:
        path = ROOT / name
        text = path.read_text(encoding='utf-8')
        doc = json.loads(text)
        report = {}
        hashed = hash_document(doc, pool, report, extra=FILE_KEYS.get(name, frozenset()))
        forms = {}
        _count(hashed, forms)
        changed = hashed != doc
        if pool.resolve_doc(hashed) != pool.resolve_doc(doc):       # the build must receive exactly the same strings
            raise SystemExit(f'{name}: hashing would change the resolved document; refusing')
        stale += changed
        if changed and not args.check:
            exact = None
            for indent in (1, 2):
                for ascii_ in (False, True):
                    if json.dumps(doc, indent=indent, ensure_ascii=ascii_) + '\n' == text:
                        exact = (indent, ascii_)
            if exact:
                out = json.dumps(hashed, indent=exact[0], ensure_ascii=exact[1]) + '\n'
            else:
                out = _swap_text(text, doc, hashed)
            path.write_text(out, encoding='utf-8')
        print(f'{name}: {"literal text found" if changed else "already references"}; '
              f'{sum(report.values())} fields hashed now {dict(sorted(report.items(), key=str))}; references in file {forms}')
    return 1 if (args.check and stale) else 0


if __name__ == '__main__':
    raise SystemExit(main())
