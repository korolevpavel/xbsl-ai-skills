"""Guard generated XBSL examples against APIs removed in Element 10.0."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def xbsl_examples():
    paths = [*ROOT.glob("skills/**/*.md"), ROOT / "docs/xbsl-spec.md", ROOT / "docs/xbsl-compat-10.md"]
    for path in paths:
        for match in re.finditer(r"```xbsl\n(.*?)\n```", path.read_text(encoding="utf-8"), re.S):
            yield path, match.group(1)


def has_untyped_fold_with_initial_value(code: str) -> bool:
    """A top-level comma in an untyped Свернуть call means the removed overload."""
    for match in re.finditer(r"\.Свернуть\s*\(", code):
        depth = 0
        for char in code[match.end():]:
            if char == "(":
                depth += 1
            elif char == ")":
                if depth == 0:
                    break
                depth -= 1
            elif char == "," and depth == 0:
                return True
    return False


def test_active_xbsl_examples_avoid_removed_element_10_apis() -> None:
    for path, code in xbsl_examples():
        assert not has_untyped_fold_with_initial_value(code), path
        assert not re.search(r"ПрочитатьОбъект\s*\([\s\S]*?Коллекция\s*<\s*Тип", code), path
        assert not re.search(r"КлючЗаписи\s*\.\s*КлючОсновногоФильтра", code), path
        assert "ПрочитатьСодержимоеКакМассив(" not in code, path
        assert "ПрочитатьСодержимоеКакСоответствие(" not in code, path


def test_json_reader_example_advances_explicitly_for_element_10() -> None:
    spec = (ROOT / "docs/xbsl-spec.md").read_text(encoding="utf-8")
    compatibility = (ROOT / "docs/xbsl-compat-10.md").read_text(encoding="utf-8")
    example = next(code for _, code in xbsl_examples() if "ПрочитатьСодержимое<" in code)
    assert "Чтение.Следующий()" in example.split("ПрочитатьСодержимое<", 1)[1]
    assert "режиме совместимости 10.0" in compatibility
    assert "xbsl-compat-10.md" in spec
