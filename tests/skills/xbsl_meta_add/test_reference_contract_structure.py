from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REFERENCE_CONTRACT = (
    REPOSITORY_ROOT
    / ".claude"
    / "skills"
    / "xbsl-meta-add"
    / "references"
    / "reference-contract.md"
)
RENDERER_PATH = REPOSITORY_ROOT / "scripts" / "render_xbsl_meta_add_coverage.py"

EXPECTED_SECTIONS = [
    "Назначение",
    "Версия и источники",
    "YAML",
    "UUID",
    "Imports и visibility",
    "Companion artifacts",
    "Генерация",
    "Валидация",
    "Runtime evidence",
    "Platform facts и local conventions",
]


def load_renderer():
    assert RENDERER_PATH.exists(), "missing #89 coverage renderer"
    spec = importlib.util.spec_from_file_location("coverage_renderer", RENDERER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def section_names(text: str) -> list[str]:
    return re.findall(r"(?m)^## (.+?)\s*$", text)


def test_reference_contract_has_exact_sections_and_fact_boundaries():
    renderer = load_renderer()
    assert REFERENCE_CONTRACT.exists(), "missing shared reference contract"
    text = REFERENCE_CONTRACT.read_text(encoding="utf-8")

    assert section_names(text) == EXPECTED_SECTIONS
    assert "Не применяется — <source-backed reason>" in text
    assert "Platform facts" in text
    assert "Local conventions" in text
    renderer.validate_reference_contract(text)


def test_reference_contract_validation_rejects_missing_or_reordered_sections():
    renderer = load_renderer()
    text = REFERENCE_CONTRACT.read_text(encoding="utf-8")
    without_yaml = text.replace("## YAML\n", "", 1)
    reordered = text.replace("## YAML\n", "## Runtime evidence\n", 1)

    with pytest.raises(renderer.CoverageValidationError, match="ten sections"):
        renderer.validate_reference_contract(without_yaml)
    with pytest.raises(renderer.CoverageValidationError, match="ten sections"):
        renderer.validate_reference_contract(reordered)


def test_reference_contract_validation_rejects_unexplained_not_applicable():
    renderer = load_renderer()
    text = REFERENCE_CONTRACT.read_text(encoding="utf-8")
    broken = text.replace(
        "Не применяется — <source-backed reason>",
        "Не применяется",
        1,
    )

    with pytest.raises(renderer.CoverageValidationError, match="source-backed"):
        renderer.validate_reference_contract(broken)
