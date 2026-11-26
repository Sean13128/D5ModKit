"""Offline admission checks only: synthetic paths, no game assets or builds."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

from d5lib import offlinepaths as paths

REPO = Path(__file__).resolve().parents[1]


class OfflinePathTests(unittest.TestCase):
    def test_new_descendant_ancestor_and_symlink_overlap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            protected = root / 'source'
            protected.mkdir()
            (protected / 'data').write_bytes(b'synthetic')
            alias = root / 'alias'
            alias.symlink_to(protected, target_is_directory=True)
            before = sorted(str(p) for p in root.rglob('*'))
            for output in (protected / 'new/deep/file', alias / 'new/file', root):
                with self.subTest(output=output), self.assertRaisesRegex(ValueError, 'overlaps'):
                    paths.offline_output(output, (protected,))
            self.assertTrue(paths.contains(protected, alias / 'new/file'))
            self.assertTrue(paths.overlaps(alias / 'data', protected / 'data'))
            self.assertEqual(before, sorted(str(p) for p in root.rglob('*')))
            valid = root / 'private/new/file'
            self.assertEqual(paths.offline_output(valid, (protected,)), valid.resolve())
            self.assertFalse(valid.parent.exists())

    def test_repository_case_alias_on_actual_volume(self):
        alias = REPO.with_name(REPO.name.swapcase())
        if not alias.exists() or not alias.samefile(REPO):
            self.skipTest('repository volume has no samefile case alias')
        output = alias / ('guard-' + uuid.uuid4().hex) / 'new.json'
        self.assertFalse(output.parent.exists())
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            paths.offline_output(output, (REPO,))
        self.assertFalse(output.parent.exists())

    def test_distinct_case_sensitive_directories_stay_distinct(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            protected, private = root / 'Source', root / 'source'
            protected.mkdir()
            if private.exists():
                self.skipTest('temporary volume is case-insensitive')
            private.mkdir()
            self.assertFalse(paths.overlaps(protected, private))
            self.assertEqual(paths.offline_output(private / 'new', (protected,)), private / 'new')

    def test_steam_marker_is_case_insensitive_and_adjacent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for output in (root / 'SteamApps/Common/Game/new', root / 'STEAMAPPS/COMMON/new'):
                with self.subTest(output=output), self.assertRaisesRegex(ValueError, 'Steam'):
                    paths.offline_output(output)
                self.assertFalse(output.parent.exists())
            valid = root / 'steamapps/offline/common/new'
            self.assertEqual(paths.offline_output(valid), valid)

    def test_input_file_and_cache_symlink_are_protected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            game = root / 'game'
            game.mkdir()
            cache = root / 'new.cache'
            cache.symlink_to(game, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'overlaps'):
                paths.offline_output(cache, (game,))
            source = root / 'extracted.obf'
            source.write_bytes(b'synthetic')
            with self.assertRaises(ValueError):
                paths.offline_output(source, (source,))
            self.assertEqual(paths.offline_output(root / 'converted.obf', (source,)), root / 'converted.obf')

    def test_mutually_written_future_paths_use_conservative_case_policy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / 'FutureBuild'
            for cache in (root / 'futurebuild', root / 'FUTUREBUILD/child'):
                with self.subTest(cache=cache), self.assertRaisesRegex(ValueError, 'destinations must be separate'):
                    paths.separate_outputs(output, cache)
                self.assertFalse(cache.exists())
            paths.separate_outputs(output, root / 'futurebuild.cache')
            self.assertFalse(output.exists())
            composed, decomposed = root / 'Futur\u00e9', root / 'Future\u0301'
            with self.assertRaisesRegex(ValueError, 'destinations must be separate'):
                paths.separate_outputs(composed, decomposed)
            self.assertFalse(composed.exists())
            self.assertFalse(decomposed.exists())


class EarlyAdmissionTests(unittest.TestCase):
    def build_args(self, tool, missing, out, game=None):
        game = game or missing
        if tool == 'build_source_pack.py':
            args = [part for flag in ('prepared-root', 'library-root', 'source-archive', 'face-path', 'cutin-path')
                    for part in ('--' + flag, missing)]
            return args + ['--game-path', game, '--output-path', out, '--family', '1350', '--template', '1150',
                '--supported-families', '1350', '--source-ids', *map(str, range(1080,1086)), '--edition', 'synthetic']
        flags = ('d4-root', 'original-state', 'mods-root') if tool == 'build_d4_unique.py' else (
            'generic-build', 'unique-build', 'original-state', 'current-kit')
        return [part for flag in flags for part in ('--' + flag, missing)] + ['--game-path', game, '--output-path', out]

    def run_cli(self, tool, args, output):
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
        result = subprocess.run([sys.executable, str(REPO / 'tools' / tool), *map(str, args)],
                                env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('Offline output', result.stderr)
        self.assertFalse(output.exists())
        self.assertFalse(Path(str(output) + '.cache').exists())
        return result

    def test_all_six_cli_guards_precede_missing_input_reads(self):
        alias = REPO.with_name(REPO.name.swapcase())
        if not alias.exists() or not alias.samefile(REPO):
            alias = REPO
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / 'missing'
            for tool in ('d4_inventory.py', 'translate_d4_scene.py', 'convert_d4_effect.py',
                         'build_source_pack.py', 'build_d4_unique.py', 'build_d4_expansion.py'):
                out = alias / ('guard-' + uuid.uuid4().hex)
                if tool == 'd4_inventory.py':
                    args = ['--d4', missing, '--output', out]
                elif tool == 'translate_d4_scene.py':
                    args = ['--d4', missing, '--receiver-script', missing, '--output', out]
                elif tool == 'convert_d4_effect.py':
                    args = [missing, out]
                else:
                    args = self.build_args(tool, missing, out)
                with self.subTest(tool=tool):
                    self.run_cli(tool, args, out)

    def test_build_wrappers_refuse_cache_redirects_before_copy_or_read(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            game = root / 'game'
            game.mkdir()
            for tool in ('build_source_pack.py', 'build_d4_unique.py', 'build_d4_expansion.py'):
                for redirect in ('game', 'output', 'future-case-alias'):
                    out = root / (tool + '-' + redirect)
                    cache = Path(str(out) + '.cache')
                    target = game if redirect == 'game' else out if redirect == 'output' else out.with_name(out.name.swapcase())
                    cache.symlink_to(target, target_is_directory=True)
                    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
                    result = subprocess.run([sys.executable, str(REPO / 'tools' / tool),
                        *map(str, self.build_args(tool, root / 'missing', out, game))],
                        env=env, capture_output=True, text=True)
                    with self.subTest(tool=tool, redirect=redirect):
                        self.assertEqual(result.returncode, 2, result.stderr)
                        self.assertIn('Offline output', result.stderr)
                        self.assertFalse(out.exists())
                        self.assertEqual(list(game.iterdir()), [])
                        self.assertTrue(cache.is_symlink())
                    cache.unlink()

    def test_builder_apis_refuse_dangling_cache_case_alias_before_readers(self):
        from d5lib import d4expansion, d4unique, sourceimports
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / 'FutureBuild'
            cache = root / 'FutureBuild.cache'
            cache.symlink_to(root / 'futurebuild', target_is_directory=True)
            with patch.object(sourceimports, 'read_prepared', side_effect=AssertionError('input read')):
                with self.assertRaisesRegex(ValueError, 'destinations must be separate'):
                    sourceimports.build_d4_pilot(prepared_root=root / 'art', library_root=root / 'lib',
                        source_archive=root / 'archive', game_path=root / 'game', face_path=root / 'face', cutin_path=root / 'cutin',
                        output_path=out, family=1350, template=1150, supported_families=[1350],
                        source_ids=list(range(1080,1086)), edition='synthetic')
            with patch.object(d4unique, 'Originals', side_effect=AssertionError('input read')):
                with self.assertRaisesRegex(ValueError, 'destinations must be separate'):
                    d4unique.build(d4_root=root / 'source', game_path=root / 'game', original_state=root / 'state',
                                   mods_roots=[root / 'mods'], output_path=out)
            with patch.object(d4expansion, 'read_pilot', side_effect=AssertionError('input read')):
                with self.assertRaisesRegex(ValueError, 'destinations must be separate'):
                    d4expansion.build(generic_build=root / 'generic', unique_build=root / 'unique',
                        game_path=root / 'game', original_state=root / 'state', current_kit=root / 'kit', output_path=out)
            self.assertFalse(out.exists())
            self.assertFalse((root / 'futurebuild').exists())
            self.assertTrue(cache.is_symlink())

    def test_worker_paths_refuse_two_missing_case_aliases_before_reads_or_writes(self):
        from d5lib import d4expansion
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for names in (('FutureBuild', 'futurebuild'), ('Futur\u00e9', 'Future\u0301')):
                output, cache = (root / name for name in names)
                values = dict(output=str(output), cache=str(cache), game_path=str(root / 'game'),
                              original_state=str(root / 'state'), mods=[])
                config = root / 'config.json'
                config.write_text(json.dumps(values))
                with self.subTest(names=names):
                    self.run_cli('build_d4_expansion.py', ['--finalize-config', config], output)
                    with self.assertRaisesRegex(ValueError, 'destinations must be separate'):
                        d4expansion.finalize(values)
                    self.assertFalse(output.exists())
                    self.assertFalse(cache.exists())

    def test_builders_refuse_before_data_read_or_cache_creation(self):
        from d5lib import d4expansion, d4unique, sourceimports
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            game = root / 'game'
            game.mkdir()
            out = game / 'new'
            with patch.object(sourceimports, 'read_prepared', side_effect=AssertionError('input read')):
                with self.assertRaisesRegex(ValueError, 'Offline output'):
                    sourceimports.build_d4_pilot(prepared_root=root / 'art', library_root=root / 'lib',
                        source_archive=root / 'archive', game_path=game, face_path=root / 'face', cutin_path=root / 'cutin',
                        output_path=out, family=1350, template=1150, supported_families=[1350],
                        source_ids=list(range(1080,1086)), edition='synthetic')
            with patch.object(d4unique, 'Originals', side_effect=AssertionError('input read')):
                with self.assertRaisesRegex(ValueError, 'Offline output'):
                    d4unique.build(d4_root=root / 'source', game_path=game, original_state=root / 'state',
                                   mods_roots=[root / 'mods'], output_path=out)
            with patch.object(d4expansion, 'read_pilot', side_effect=AssertionError('input read')):
                with self.assertRaisesRegex(ValueError, 'Offline output'):
                    d4expansion.build(generic_build=root / 'generic', unique_build=root / 'unique',
                        game_path=game, original_state=root / 'state', current_kit=root / 'kit', output_path=out)
            self.assertFalse(out.exists())
            self.assertFalse(Path(str(out) + '.cache').exists())

    def test_worker_config_refuses_cache_before_imports_or_creation(self):
        from d5lib import d4expansion
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            game = root / 'game'
            game.mkdir()
            output = root / 'private-new'
            cache = game / 'new-cache'
            config = root / 'config.json'
            values = dict(output=str(output), cache=str(cache),
                game_path=str(game), original_state=str(root / 'state'), mods=[])
            config.write_text(json.dumps(values))
            self.run_cli('build_d4_expansion.py', ['--finalize-config', config], output)
            with self.assertRaisesRegex(ValueError, 'Offline output'):
                d4expansion.finalize(values)
            self.assertFalse(cache.exists())

    def test_effect_report_cannot_replace_its_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / 'new.obf'
            source = root / 'new.obf.json'
            source.write_bytes(b'synthetic preserved source')
            self.run_cli('convert_d4_effect.py', [source, output], output)
            self.assertEqual(source.read_bytes(), b'synthetic preserved source')

    def test_normal_private_paths_reach_reader_without_writes(self):
        from d5lib import d4expansion, d4unique, runtime, sourceimports, sprites
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / 'private-new'
            with patch.object(sprites, 'CACHE_DIR', str(out) + '.cache'), \
                    patch.object(sourceimports, 'read_prepared', side_effect=RuntimeError('reader reached')):
                with self.assertRaisesRegex(RuntimeError, 'reader reached'):
                    sourceimports.build_d4_pilot(prepared_root=root / 'art', library_root=root / 'lib',
                        source_archive=root / 'archive', game_path=root / 'game', face_path=root / 'face', cutin_path=root / 'cutin',
                        output_path=out, family=1350, template=1150, supported_families=[1350],
                        source_ids=list(range(1080,1086)), edition='synthetic')
            with patch.object(sprites, 'CACHE_DIR', str(out) + '.cache'), \
                    patch.object(runtime, 'CACHE', str(out) + '.cache'), \
                    patch.object(d4unique, 'Originals', side_effect=RuntimeError('reader reached')):
                with self.assertRaisesRegex(RuntimeError, 'reader reached'):
                    d4unique.build(d4_root=root / 'source', game_path=root / 'game', original_state=root / 'state',
                                   mods_roots=[root / 'mods'], output_path=out)
            with patch.object(d4expansion, 'read_pilot', side_effect=RuntimeError('reader reached')):
                with self.assertRaisesRegex(RuntimeError, 'reader reached'):
                    d4expansion.build(generic_build=root / 'generic', unique_build=root / 'unique',
                        game_path=root / 'game', original_state=root / 'state', current_kit=root / 'kit', output_path=out)
            self.assertFalse(out.exists())
            self.assertFalse(Path(str(out) + '.cache').exists())

    def test_actual_cache_globals_must_match_private_sibling_before_readers(self):
        from d5lib import d4unique, runtime, sourceimports, sprites
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            game = root / 'game'
            game.mkdir()
            out, expected = root / 'private-new', root / 'private-new.cache'
            def source_call():
                return sourceimports.build_d4_pilot(prepared_root=root / 'art', library_root=root / 'lib',
                    source_archive=root / 'archive', game_path=game, face_path=root / 'face', cutin_path=root / 'cutin',
                    output_path=out, family=1350, template=1150, supported_families=[1350],
                    source_ids=list(range(1080,1086)), edition='synthetic')
            def unique_call(finalize=True):
                return d4unique.build(d4_root=root / 'source', game_path=game, original_state=root / 'state',
                    mods_roots=[root / 'mods'], output_path=out, finalize=finalize)
            for bad in (game / 'cache', root / 'wrong-private-cache'):
                with patch.object(sprites, 'CACHE_DIR', str(bad)), \
                        patch.object(sourceimports, 'read_prepared', side_effect=AssertionError('input read')):
                    with self.assertRaisesRegex(ValueError, 'Configure private per-output caches'):
                        source_call()
                    self.assertEqual(sprites.CACHE_DIR, str(bad))
                with patch.object(sprites, 'CACHE_DIR', str(bad)), \
                        patch.object(d4unique, 'Originals', side_effect=AssertionError('input read')):
                    with self.assertRaisesRegex(ValueError, 'Configure private per-output caches'):
                        unique_call(False)
                with patch.object(sprites, 'CACHE_DIR', str(expected)), patch.object(runtime, 'CACHE', str(bad)), \
                        patch.object(d4unique, 'Originals', side_effect=AssertionError('input read')):
                    with self.assertRaisesRegex(ValueError, 'Configure private per-output caches'):
                        unique_call()
                    self.assertEqual(runtime.CACHE, str(bad))
                self.assertFalse(bad.exists())
            # No runtime finalization means that unrelated runtime cache is unused.
            with patch.object(sprites, 'CACHE_DIR', str(expected)), patch.object(runtime, 'CACHE', str(game / 'cache')), \
                    patch.object(d4unique, 'Originals', side_effect=RuntimeError('reader reached')):
                with self.assertRaisesRegex(RuntimeError, 'reader reached'):
                    unique_call(False)
            self.assertFalse(out.exists())
            self.assertFalse(expected.exists())
            self.assertEqual(list(game.iterdir()), [])
            self.assertEqual(list(root.rglob('resident_ids.pickle')), [])

    def test_normal_effect_cli_writes_only_private_synthetic_output(self):
        from tests.test_d4effects import model, texture
        from d5lib import d4effects
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, output = root / 'source.obf', root / 'private/new.obf'
            original = model([texture()])
            source.write_bytes(original)
            result = subprocess.run([sys.executable, str(REPO / 'tools/convert_d4_effect.py'), str(source), str(output)],
                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_bytes(), d4effects.convert_obf(original)[0])
            self.assertTrue(output.with_suffix('.obf.json').is_file())
            self.assertEqual(source.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
