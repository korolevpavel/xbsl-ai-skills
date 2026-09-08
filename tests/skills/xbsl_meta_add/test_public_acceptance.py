from __future__ import annotations

import importlib.util
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR_PATH = (
    REPOSITORY_ROOT
    / "skills"
    / "xbsl-validate"
    / "scripts"
    / "validate.py"
)
META_ADD_ROOT = REPOSITORY_ROOT / "skills" / "xbsl-meta-add"
FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures"


def load_validator():
    spec = importlib.util.spec_from_file_location("xbsl_validate", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_examples_and_positive_fixtures_pass_xbsl_validate(capsys):
    validator = load_validator()

    code = validator.main(
        [
            str(META_ADD_ROOT / "examples"),
            str(FIXTURES_ROOT / "data-and-execution" / "positive"),
            str(FIXTURES_ROOT / "contracts-and-reports" / "positive"),
            str(FIXTURES_ROOT / "security-and-events" / "positive"),
            str(FIXTURES_ROOT / "integration" / "positive"),
        ]
    )
    captured = capsys.readouterr()

    assert code == 0, captured.out
    assert captured.out == ""
    assert captured.err == ""
