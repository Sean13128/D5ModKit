"""Simple D4 source voice conversion using the normal Kit voices API; no native hooks."""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def basic_event_map():
    """Explicit playtest adaptations; D5 owns timing and random choice.

    Category 11 is D4's whole-bank voice preview, not a general-purpose bark.
    Unresolved reaction/skill categories are deliberately not guessed here.
    """
    return {
        '0': [dict(kind=0, cats=[0], event='basic attack',
                   evidence='D4 weapon attack event11100001; D5 attack-entry category0')],
        '2': [dict(kind=0, cats=[4], event='elemental casting',
                   evidence='D4 shared elemental cast event12000074; D5 elemental cast event12000074')],
        '4': [dict(kind=0, cats=[9], event='healing casting',
                   evidence='D4 alternate healing cast event12000074; D5 healing cast event12000074')],
        '5': [dict(kind=0, cats=[10], event='lift',
                   evidence='Original carrier attachment callers and selector trace')],
        '6': [dict(kind=0, cats=[11], event='throw',
                   evidence='D4 carrier throw/landing controller; D5 throw controller category11')],
        '7': [dict(kind=0, cats=[13], event='move/landing',
                   evidence='D4 callers 0x1403050a0/0x140304270 emit category7 after the hop '
                            'destination snap; D5 0x14052e920/0x14052d500/0x140853720 run the same '
                            'snap and speak situation 0xd')],
    }


def import_d4_voice(mod, source, *, voice_id, groups, event_map, occupied_ids=(), peak_limit=0.85,
                    source_language=None, destination_language=None):
    """Simple source PCM conversion into the Kit's existing personality voices.

    Event choices are explicit adaptations supplied by the caller. D5 owns the
    timing and randomizer. Source gain / 100 is baked into PCM and peak-limited;
    RIFF rate drives the Kit's normal resampling to 48 kHz. This is a loudness adaptation, not a native
    playback reconstruction. Every unrouted clip remains in the gap receipt.
    """
    import math
    from types import SimpleNamespace
    if source_language is not None:
        if source_language not in ("EN", "JP"):
            raise ValueError("Unsupported D4 source voice language")
        if source_language != getattr(source, "lang", "EN"):
            from . import d4source
            reader = SimpleNamespace(root=source.root, lang=source_language,
                                     _locate=getattr(source, "_locate", None))
            reader._file = lambda rel: d4source.D4Data._file(reader, rel)
            reader.voice_lines = lambda groups: d4source.D4Data.voice_lines(reader, groups)
            source = reader
    if destination_language not in (None, "EN", "JP"):
        raise ValueError("Unsupported D5 destination voice language")
    if destination_language is not None and getattr(source, "lang", "EN") != destination_language:
        raise ValueError("Explicit locale import requires matching source language")
    import numpy as np
    from . import sfx, voices, sound
    if type(voice_id) is not int or not voices.CUSTOM_FIRST <= voice_id <= voices.CUSTOM_LAST or voice_id in occupied_ids:
        raise ValueError('Explicit free custom voice lease required')
    if (not isinstance(groups, list) or not 1 <= len(groups) <= 3 or len(set(groups)) != len(groups)
            or any(type(g) is not int or g < 0 for g in groups)):
        raise ValueError('Supply one to three distinct source personality groups')
    if not math.isfinite(peak_limit) or not 0 < peak_limit <= 1:
        raise ValueError('Invalid voice peak limit')
    routes = {}
    route_provenance = {}
    for category, targets in event_map.items():
        category = int(category)
        if not 0 <= category < 12:
            raise ValueError('D4 voice category outside 0..11')
        for target in targets:
            kind, cats = target['kind'], target['cats']
            if type(kind) is not int or not 0 <= kind < 4 or not cats or any(type(c) is not int or not 0 <= c < 34 for c in cats):
                raise ValueError('Invalid D5 voice destination')
            routes.setdefault(category, []).append((kind, tuple(cats)))
            route_provenance.setdefault(category, []).append(dict(target))
    data = voices.load(mod)
    previous = data['voices'].get(str(voice_id), {}).get('lines', [])
    if destination_language is not None and any('files' not in line for line in previous):
        raise ValueError('Explicit locale import cannot mix legacy mirrored voice lines')
    if destination_language is not None:
        for line in previous:
            for lang in voices.TABLES:
                voices._custom_source(line, lang)
    lines, receipt = [], []
    source_clips = source.voice_lines(groups)
    if len({clip['line'] for clip in source_clips}) != len(source_clips):
        raise ValueError('Duplicate source voice line')
    for clip in source_clips:
        selected = {}
        for category in clip['native_active_categories']:
            for kind, cats in routes.get(category, []):
                selected.setdefault(kind, set()).update(cats)
        unresolved = [c for c in clip['native_active_categories'] if c not in routes]
        item = dict(line=clip['line'], source_group=clip['group'], personality=groups.index(clip['group']),
                    source_categories=clip['native_active_categories'], source_gain=clip['volume_raw'],
                    riff_sha256=_hash(clip['riff']), destinations={str(k): sorted(v) for k,v in selected.items()})
        item.update(source_uid=f"d4:{getattr(source, 'lang', 'EN')}:voice-line:{clip['line']}:row:{clip.get('table_row_index', 'unknown')}",
                    source_voice_group_base=groups[0], source_rate_input_signed=clip.get('native_rate_input_signed'),
                    wrapper_hex=clip.get('wrapper_hex'), wrapper_u32=clip.get('wrapper_u32'),
                    route_provenance={str(c): route_provenance[c] for c in clip['native_active_categories'] if c in routes},
                    unrouted_categories={str(c): ('Whole-bank D4 preview only; does not establish a battle event' if c == 11
                                                else 'Source event semantic role has no reviewed D5 destination') for c in unresolved})
        if clip.get('wrapper_hex'):
            item['wrapped_source_sha256'] = _hash(bytes.fromhex(clip['wrapper_hex']) + clip['riff'])
        if 'native_category_flags' in clip and 'native_rate_input_signed' in clip:
            row = struct.pack('<IIfi12I', clip['line'], clip['group'], clip['volume_raw'],
                              clip['native_rate_input_signed'], *clip['native_category_flags'])
            item['source_row_sha256'] = _hash(row)
        if not selected:
            reason = ('Direct-only source clip; its source skill/scene has no D5 direct-line remap in this playtest'
                      if not clip['native_active_categories'] else
                      'Only unresolved source categories or the whole-bank preview bucket; no invented trigger')
            receipt.append(dict(item, status='unrouted-placeholder', reason=reason))
            continue
        pcm, rate = sfx.read_wav(clip['riff'])
        gain = clip['volume_raw'] / 100
        if not math.isfinite(gain) or gain < 0:
            raise ValueError('Invalid source voice gain')
        if not np.isfinite(pcm).all() or not pcm.size:
            raise ValueError('Empty or nonfinite source PCM')
        pcm = sfx.resample(np.asarray(pcm, dtype=np.float32), rate) * gain
        peak = float(np.max(np.abs(pcm))) if pcm.size else 0
        limit_scale = min(1.0, peak_limit / peak) if peak else 1.0
        pcm *= limit_scale
        raw = sfx.make_vag(pcm, sfx.RATE, normalize=False, trim=False)
        decoded, output_rate = sfx.read_wav(sound.parse_se(raw)['wav'])
        output_peak = float(np.max(np.abs(decoded))) if decoded.size else 0
        # ADPCM quantisation can overshoot the PCM limiter. Correct the encoded
        # result with bounded gain-only retries, never trimming or normalising.
        for _ in range(3):
            if output_peak <= peak_limit + 1e-5:
                break
            scale = peak_limit / output_peak * 0.98
            pcm *= scale
            limit_scale *= scale
            raw = sfx.make_vag(pcm, sfx.RATE, normalize=False, trim=False)
            decoded, output_rate = sfx.read_wav(sound.parse_se(raw)['wav'])
            output_peak = float(np.max(np.abs(decoded))) if decoded.size else 0
        if output_rate != sfx.RATE or output_peak > peak_limit + 1e-5 or not np.isfinite(decoded).all():
            raise ValueError('Converted D4 voice fails output rate/peak/finite checks')
        filename = f'd4_{voice_id}_{clip["line"]}' + (f'_{destination_language}' if destination_language else '') + '.vag'
        path = Path(voices.folder(mod)) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        for kind, cats in selected.items():
            line = dict(kind=kind, cats=sorted(cats), personality=item['personality'], volume=voices.DEFAULT_VOLUME)
            if destination_language is None:
                line['file'] = filename
            else:
                line.update(files={destination_language: filename}, missing_locale='silence')
            lines.append(line)
        receipt.append(dict(item, status='converted-adapted', output_sha256=_hash(raw), riff_sample_rate=rate,
                            baked_gain=gain * limit_scale, peak_limit=peak_limit, output_rate=output_rate,
                            output_peak=output_peak, output_samples=len(decoded)))
    if not lines:
        raise ValueError('Voice map selects no source clips')
    if destination_language is not None:
        retained = []
        for line in previous:
            files = {lang: name for lang, name in line['files'].items() if lang != destination_language}
            if files:
                # Keep other locales' routes, but do not retain a fallback into the locale being replaced.
                kept = dict(line, files=files, missing_locale='silence')
                kept.pop('fallback_language', None)
                retained.append(kept)
        lines = retained + lines
    data['voices'][str(voice_id)] = dict(name='D4 source voice', lines=lines)
    voices.save(mod, data)
    return dict(voice_id=voice_id, groups=groups, clips=receipt, native_tested=False,
                source_language=getattr(source, 'lang', 'EN'), destination_language=destination_language,
                locale_policy='explicit per-language files; missing locale silent' if destination_language else 'legacy same custom file in both locales',
                adaptation='Source gain/100 baked into PCM with peak limiter; RIFF rate drives Kit 48kHz resampling; D5 triggers/randomizer; explicit routes only')


def source_voice_facts(d4root, row_id, locate=None):
    """What Disgaea 4's own voice containers hold for a char row, both dubs (VOICESILENT1, shared by
    tools/stage_d4_silent.py and the importer, REPROFIX4).  The row's groups are its voice group, its body id and
    the voice group of the row that body names (Pringer X 210 <-> Pringer X: Roar 5405).
    -> dict(row, name, body, groups, per_lang={lang: dict(table_rows, archive_members, table_total, archive_total)})"""
    import collections
    from pathlib import Path
    from . import d4source, fafs
    d4 = d4source.D4Data(d4root, "EN", locate=locate)
    row = d4.chars[row_id]
    groups = {row["voice_group_base"], row["body"]}
    partner = d4.chars.get(row["body"])
    if partner:
        groups.add(partner["voice_group_base"])
    out = dict(row=row_id, name=row["name"], body=row["body"], groups=sorted(groups), per_lang={})
    for lang in ("EN", "JP"):
        where = (locate if locate is not None else (lambda rel: Path(d4root) / rel))
        table = d4source.decode_voice_table(Path(where(d4source.VOICE_TABLE.format(lang=lang))).read_bytes())
        pack = fafs.FafsPack(str(where(d4source.VOICE_PACK.format(lang=lang))))
        try:
            names = [e.name for e in pack.entries]
        finally:
            pack.close()
        dirs = collections.Counter(n.split("/")[1] for n in names if n.count("/") >= 2)
        out["per_lang"][lang] = dict(
            table_rows=sum(1 for r in table.values() if r["group"] in groups),
            archive_members=sum(dirs.get(str(g), 0) for g in groups),
            table_total=len(table), archive_total=len(names))
    return out


def source_has_voice(facts):
    return any(v["table_rows"] or v["archive_members"] for v in facts["per_lang"].values())


def silent_why(facts):
    g = " and ".join(str(x) for x in facts["groups"])
    return (f"Disgaea 4 Complete+: voice group {g} not found in the voice table or the voice archive of either dub "
            f"(SoundData_Voice_EN/JP.dat, EN/JP voice.dat)")
