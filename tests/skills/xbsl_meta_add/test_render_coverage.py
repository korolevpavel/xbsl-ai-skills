from __future__ import annotations

import importlib.util
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = REPOSITORY_ROOT / ".claude" / "skills" / "xbsl-meta-add"
COVERAGE_PATH = SKILL_ROOT / "object-coverage.json"
MARKDOWN_PATH = SKILL_ROOT / "object-coverage.md"
RENDERER_PATH = REPOSITORY_ROOT / "scripts" / "render_xbsl_meta_add_coverage.py"


def load_renderer():
    assert RENDERER_PATH.exists(), "missing #89 coverage renderer"
    spec = importlib.util.spec_from_file_location("coverage_renderer", RENDERER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rendered_markdown_is_deterministic_and_committed():
    renderer = load_renderer()
    data = renderer.load_coverage(COVERAGE_PATH)

    rendered = renderer.render_markdown(data)

    assert rendered == renderer.render_markdown(data)
    assert rendered.startswith("# Матрица покрытия xbsl-meta-add\n")
    assert "1С:Предприятие.Элемент 9.2" in rendered
    assert "`12 supported + 19 partial + 1 routed = 32`" in rendered
    assert "| `ЗапланированноеЗадание` | `routed` | `xbsl-scheduled-task` | #3 |" in rendered
    assert MARKDOWN_PATH.read_text(encoding="utf-8") == rendered


def test_renderer_check_is_read_only_when_markdown_is_stale(tmp_path):
    renderer = load_renderer()
    output = tmp_path / "object-coverage.md"
    output.write_text("stale\n", encoding="utf-8")

    result = renderer.main(
        [
            "--coverage",
            str(COVERAGE_PATH),
            "--output",
            str(output),
            "--check",
        ]
    )

    assert result == 1
    assert output.read_text(encoding="utf-8") == "stale\n"


def test_renderer_default_check_accepts_repository_copy():
    renderer = load_renderer()
    assert renderer.main(["--check"]) == 0
