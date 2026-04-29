"""Тесты для .claude/skills/xbsl-lib-connect/scripts/lib_connect.py"""

import importlib.util
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).parents[3] / '.claude' / 'skills' / 'xbsl-lib-connect' / 'scripts' / 'lib_connect.py'


@pytest.fixture
def lc():
    spec = importlib.util.spec_from_file_location('lib_connect', SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_main(lc, monkeypatch, capsys, argv: list[str]) -> tuple:
    monkeypatch.setattr(sys, 'argv', ['lib_connect.py'] + argv)
    exit_code = 0
    try:
        lc.main()
    except SystemExit as e:
        exit_code = e.code or 0
    captured = capsys.readouterr()
    return captured, exit_code


def make_xlib(path: Path, project_kind: str = 'Library',
              vendor: str = 'e1c', name: str = 'TestLib',
              version: str = '1.0-5', tech_version: str = '') -> Path:
    """Создать минимальный .xlib ZIP-архив для тестов."""
    assembly_lines = [
        'ManifestVersion: 1.0',
        f'ProjectKind: {project_kind}',
        f'Vendor: {vendor}',
        f'Name: {name}',
        f'Version: {version}',
    ]
    if tech_version:
        assembly_lines.append(f'TechnologyVersion: {tech_version}')
    assembly = '\n'.join(assembly_lines) + '\n'

    xlib_path = path / f'{name}.xlib'
    with zipfile.ZipFile(xlib_path, 'w') as zf:
        zf.writestr('Assembly.yaml', assembly)
    return xlib_path


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------

class TestInspect:
    def test_valid_library(self, lc, monkeypatch, capsys, tmp_path):
        xlib = make_xlib(tmp_path, tech_version='24.1')
        captured, code = run_main(lc, monkeypatch, capsys, ['--action', 'inspect', '--file', str(xlib)])
        assert code == 0
        result = json.loads(captured.out)
        assert result['vendor'] == 'e1c'
        assert result['name'] == 'TestLib'
        assert result['project_kind'] == 'Library'
        assert result['technology_version'] == '24.1'

    def test_application_returns_error(self, lc, monkeypatch, capsys, tmp_path):
        xlib = make_xlib(tmp_path, project_kind='Application')
        captured, code = run_main(lc, monkeypatch, capsys, ['--action', 'inspect', '--file', str(xlib)])
        assert code != 0
        result = json.loads(captured.out)
        assert result['error'] == 'not_a_library'

    def test_file_not_found(self, lc, monkeypatch, capsys, tmp_path):
        captured, code = run_main(lc, monkeypatch, capsys, ['--action', 'inspect', '--file', '/nonexistent.xlib'])
        assert code != 0
        assert 'file_not_found' in captured.out

    def test_not_a_zip(self, lc, monkeypatch, capsys, tmp_path):
        bad = tmp_path / 'bad.xlib'
        bad.write_text('not a zip')
        captured, code = run_main(lc, monkeypatch, capsys, ['--action', 'inspect', '--file', str(bad)])
        assert code != 0
        assert 'not_a_zip' in captured.out


# ---------------------------------------------------------------------------
# find-xlib
# ---------------------------------------------------------------------------

class TestFindXlib:
    def test_no_files(self, lc, monkeypatch, capsys, tmp_path):
        captured, code = run_main(lc, monkeypatch, capsys, ['--action', 'find-xlib', '--dir', str(tmp_path)])
        assert code == 0
        assert json.loads(captured.out) == []

    def test_single_file(self, lc, monkeypatch, capsys, tmp_path):
        xlib = make_xlib(tmp_path)
        captured, code = run_main(lc, monkeypatch, capsys, ['--action', 'find-xlib', '--dir', str(tmp_path)])
        assert code == 0
        result = json.loads(captured.out)
        assert len(result) == 1
        assert result[0] == str(xlib)

    def test_multiple_files(self, lc, monkeypatch, capsys, tmp_path):
        dist = tmp_path / 'dist'
        dist.mkdir()
        make_xlib(tmp_path, name='Lib1')
        make_xlib(dist, name='Lib2')
        make_xlib(dist, name='Lib3')
        captured, code = run_main(lc, monkeypatch, capsys, ['--action', 'find-xlib', '--dir', str(tmp_path)])
        assert code == 0
        result = json.loads(captured.out)
        assert len(result) == 3

    def test_dir_not_found(self, lc, monkeypatch, capsys):
        captured, code = run_main(lc, monkeypatch, capsys, ['--action', 'find-xlib', '--dir', '/nonexistent'])
        assert code != 0
        assert 'dir_not_found' in captured.out


# ---------------------------------------------------------------------------
# patch-yaml
# ---------------------------------------------------------------------------

def make_project_yaml(path: Path, content: str) -> Path:
    p = path / 'Проект.yaml'
    p.write_text(content, encoding='utf-8')
    return p


class TestPatchYaml:
    BASE_ARGS = ['--action', 'patch-yaml', '--name', 'TelegramBot', '--vendor', 'e1c', '--version', '1.0.0']

    def test_creates_section_when_missing(self, lc, monkeypatch, capsys, tmp_path):
        p = make_project_yaml(tmp_path, 'Ид: abc\nИмя: MyProject\n')
        run_main(lc, monkeypatch, capsys, self.BASE_ARGS + ['--project-yaml', str(p)])
        result = p.read_text(encoding='utf-8')
        assert 'Библиотеки:' in result
        assert 'TelegramBot' in result
        assert 'e1c' in result
        assert '1.0.0' in result

    def test_adds_to_existing_section(self, lc, monkeypatch, capsys, tmp_path):
        content = 'Ид: abc\nБиблиотеки:\n    -\n        Имя: OtherLib\n        Поставщик: acme\n        Версия: 2.0.0\n'
        p = make_project_yaml(tmp_path, content)
        run_main(lc, monkeypatch, capsys, self.BASE_ARGS + ['--project-yaml', str(p)])
        result = p.read_text(encoding='utf-8')
        assert 'TelegramBot' in result
        assert 'OtherLib' in result

    def test_updates_existing_version(self, lc, monkeypatch, capsys, tmp_path):
        content = (
            'Ид: abc\n'
            'Библиотеки:\n'
            '    -\n'
            '        Имя: TelegramBot\n'
            '        Поставщик: e1c\n'
            '        Версия: 0.9.0\n'
        )
        p = make_project_yaml(tmp_path, content)
        run_main(lc, monkeypatch, capsys, self.BASE_ARGS + ['--project-yaml', str(p)])
        result = p.read_text(encoding='utf-8')
        assert '1.0.0' in result
        assert '0.9.0' not in result

    def test_dry_run_does_not_write(self, lc, monkeypatch, capsys, tmp_path):
        original = 'Ид: abc\nИмя: MyProject\n'
        p = make_project_yaml(tmp_path, original)
        captured, code = run_main(lc, monkeypatch, capsys, self.BASE_ARGS + ['--project-yaml', str(p), '--dry-run'])
        assert code == 0
        assert p.read_text(encoding='utf-8') == original
        data = json.loads(captured.out)
        assert data['status'] == 'dry_run'
        assert 'before' in data
        assert 'after' in data
        assert 'TelegramBot' in data['after']

    def test_dry_run_shows_diff(self, lc, monkeypatch, capsys, tmp_path):
        p = make_project_yaml(tmp_path, 'Ид: abc\n')
        captured, _ = run_main(lc, monkeypatch, capsys, self.BASE_ARGS + ['--project-yaml', str(p), '--dry-run'])
        data = json.loads(captured.out)
        assert data['before'] != data['after']


# ---------------------------------------------------------------------------
# validate-version
# ---------------------------------------------------------------------------

class TestValidateVersion:
    @pytest.mark.parametrize('version', ['1.0.0', '2.10.3', '0.0.1', '1.0'])
    def test_valid(self, lc, monkeypatch, capsys, version):
        captured, code = run_main(lc, monkeypatch, capsys, ['--action', 'validate-version', '--version', version])
        assert code == 0
        assert json.loads(captured.out)['valid'] is True

    @pytest.mark.parametrize('version', ['1.0-5', '1.0.0-rc1', 'abc', '1.0.', '.1.0'])
    def test_invalid(self, lc, monkeypatch, capsys, version):
        captured, code = run_main(lc, monkeypatch, capsys, ['--action', 'validate-version', '--version', version])
        assert code != 0
        data = json.loads(captured.out)
        assert data['valid'] is False
        assert 'error' in data


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------

def make_xlib_with_content(path: Path) -> Path:
    """Создать .xlib с подсистемами и публичными типами."""
    assembly = (
        'ManifestVersion: 1.0\n'
        'ProjectKind: Library\n'
        'Vendor: e1c\n'
        'Name: TelegramBot\n'
        'Version: 1.0-5\n'
    )
    subsystem_yaml = (
        'ВидЭлемента: Подсистема\n'
        'Ид: aaa\n'
        'Имя: Основное\n'
        'Представление: Telegram Bot\n'
    )
    public_type_yaml = (
        'ВидЭлемента: ОбщийМодуль\n'
        'Ид: bbb\n'
        'Имя: ОтправитьСообщение\n'
        'ОбластьВидимости: Глобально\n'
    )
    private_type_yaml = (
        'ВидЭлемента: Справочник\n'
        'Ид: ccc\n'
        'Имя: ВнутренняяСущность\n'
        'ОбластьВидимости: ВПодсистеме\n'
    )

    xlib_path = path / 'TelegramBot.xlib'
    with zipfile.ZipFile(xlib_path, 'w') as zf:
        zf.writestr('Assembly.yaml', assembly)
        zf.writestr('e1c/TelegramBot/Основное/Подсистема.yaml', subsystem_yaml)
        zf.writestr('e1c/TelegramBot/Основное/ОтправитьСообщение.yaml', public_type_yaml)
        zf.writestr('e1c/TelegramBot/Основное/ВнутренняяСущность.yaml', private_type_yaml)
    return xlib_path


class TestAnalyze:
    def test_returns_subsystems_and_public_types(self, lc, monkeypatch, capsys, tmp_path):
        xlib = make_xlib_with_content(tmp_path)
        captured, code = run_main(lc, monkeypatch, capsys, ['--action', 'analyze', '--file', str(xlib)])
        assert code == 0
        data = json.loads(captured.out)
        assert data['vendor'] == 'e1c'
        assert data['name'] == 'TelegramBot'
        assert len(data['subsystems']) == 1
        assert data['subsystems'][0]['name'] == 'Основное'
        assert len(data['public_types']) == 1
        assert data['public_types'][0]['name'] == 'ОтправитьСообщение'

    def test_excludes_private_types(self, lc, monkeypatch, capsys, tmp_path):
        xlib = make_xlib_with_content(tmp_path)
        captured, code = run_main(lc, monkeypatch, capsys, ['--action', 'analyze', '--file', str(xlib)])
        data = json.loads(captured.out)
        names = [t['name'] for t in data['public_types']]
        assert 'ВнутренняяСущность' not in names

    def test_cleans_up_temp_dir(self, lc, monkeypatch, capsys, tmp_path):
        import glob
        before = set(glob.glob('/tmp/xlib_analyze_*'))
        xlib = make_xlib_with_content(tmp_path)
        run_main(lc, monkeypatch, capsys, ['--action', 'analyze', '--file', str(xlib)])
        after = set(glob.glob('/tmp/xlib_analyze_*'))
        assert after == before


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------

class TestCleanup:
    def test_removes_directory(self, lc, monkeypatch, capsys, tmp_path):
        target = tmp_path / 'xlib_src_test'
        target.mkdir()
        (target / 'file.txt').write_text('data')
        captured, code = run_main(lc, monkeypatch, capsys, ['--action', 'cleanup', '--dir', str(target)])
        assert code == 0
        assert not target.exists()
        assert json.loads(captured.out)['status'] == 'cleaned'

    def test_nonexistent_dir_does_not_fail(self, lc, monkeypatch, capsys, tmp_path):
        captured, code = run_main(lc, monkeypatch, capsys, ['--action', 'cleanup', '--dir', str(tmp_path / 'ghost')])
        assert code == 0
        assert json.loads(captured.out)['status'] == 'cleaned'
