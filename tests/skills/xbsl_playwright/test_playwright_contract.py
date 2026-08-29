"""Semantic public contract for the xbsl-playwright instruction-only skill."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT_DIR = Path(__file__).resolve().parents[3]
SKILL_DIR = ROOT_DIR / "skills" / "xbsl-playwright"
SKILL_PATH = SKILL_DIR / "SKILL.md"
REFERENCE_NAMES = {"authoring.md", "authentication.md", "run-and-debug.md"}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def frontmatter(text: str) -> dict[str, object]:
    match = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL)
    assert match is not None
    value = yaml.safe_load(match.group(1))
    assert isinstance(value, dict)
    return value


def all_public_text() -> str:
    paths = [SKILL_PATH, *(SKILL_DIR / "references").glob("*.md")]
    return "\n".join(read(path) for path in paths)


def test_frontmatter_has_discriminating_playwright_only_activation() -> None:
    meta = frontmatter(read(SKILL_PATH))

    assert meta["name"] == "xbsl-playwright"
    assert meta["metadata"] == {"runtime": "Node.js + @playwright/test"}
    description = str(meta["description"])
    for positive in ("Playwright Test", "TypeScript", "UI/E2E", "RLS", "storageState"):
        assert positive in description
    for negative in (
        "встроенного браузера",
        "deploy/cloud API",
        "XBSL/YAML-валидации",
        "API-only",
        "Python/Java/C#",
        "YaXUnit",
        "Vanessa Automation",
    ):
        assert negative in description


def test_v1_is_instruction_only_and_references_are_discoverable() -> None:
    actual_references = {
        path.name for path in (SKILL_DIR / "references").glob("*.md")
    }
    skill = read(SKILL_PATH)

    assert actual_references == REFERENCE_NAMES
    for reference in REFERENCE_NAMES:
        assert f"references/{reference}" in skill
    for forbidden_dir in ("scripts", "assets", "agents"):
        assert not (SKILL_DIR / forbidden_dir).exists()


def test_consumer_setup_and_permission_gate_are_explicit() -> None:
    skill = read(SKILL_PATH)
    authoring = read(SKILL_DIR / "references" / "authoring.md")

    for concept in (
        "dry-run",
        "явного подтверждения",
        "файлы, зависимости, браузеры и команды",
        "изменения тестовых данных",
        "Cleanup требует отдельного подтверждения",
    ):
        assert concept in skill
    normalized_skill = normalized(skill)
    assert "изолированный пакет `e2e/`" in normalized_skill
    assert "Если Playwright уже настроен, расширяй этот setup" in normalized_skill
    assert "Не заменяй config" in authoring
    assert "конфликтующих lockfiles" in skill
    assert "используй npm" in authoring
    assert "не регистрируй в существующем workspace" in authoring
    assert "не меняй корневые" in authoring
    assert "собственным" in authoring and "lockfile" in authoring


def test_authoring_preserves_url_and_playwright_defaults() -> None:
    authoring = read(SKILL_DIR / "references" / "authoring.md")

    for invariant in (
        "TypeScript",
        "@playwright/test",
        'testDir: "./tests"',
        "Chromium и один worker",
        "ELEMENT_APP_URL",
        'page.goto(process.env.ELEMENT_APP_URL!)',
        'page.goto("/")',
        'trace: "retain-on-failure"',
        'screenshot: "only-on-failure"',
        'video: "off"',
        "CI-конфигурация отсутствует",
    ):
        assert invariant in authoring
    assert ".auth/" in authoring
    assert "test-results/" in authoring
    assert "playwright-report/" in authoring
    assert "blob-report/" in authoring


def test_semantic_locators_assertions_and_data_safety_are_required() -> None:
    authoring = read(SKILL_DIR / "references" / "authoring.md")

    for locator in (
        "getByRole",
        "getByLabel",
        "getByPlaceholder",
        "getByText",
        "data-testid",
    ):
        assert locator in authoring
    for unstable in ("XPath", "внутренние CSS", "координатные клики", "waitForTimeout"):
        assert unstable in authoring
    assert "web-first assertions" in authoring
    assert "уникальный run ID" in authoring
    assert "BLOCKED/PRECONDITION" in authoring
    assert "не выбирай случайный первый элемент" in authoring
    assert "Широкие условия удаления запрещены" in authoring


def test_authentication_is_interactive_isolated_and_secret_safe() -> None:
    auth = read(SKILL_DIR / "references" / "authentication.md")
    normalized_auth = normalized(auth)

    for invariant in (
        "ELEMENT_AUTH_STATE",
        "Независимо от источника auth state",
        "Никогда не открывай, не разбирай, не печатай и не прикладывай",
        "headed Chromium",
        "новый независимый browser context",
        "/sys/auth/authorization/",
        "auth.1cmycloud.com/.../signin",
        "sessionStorage",
        "BLOCKED/AUTH",
        "отдельный `.auth/*.json`",
        "не публикуй",
    ):
        assert invariant in normalized_auth
    assert '"$ELEMENT_APP_URL"' in auth
    assert '"$env:ELEMENT_APP_URL"' in auth


def test_status_reason_and_repair_contract_is_complete() -> None:
    skill = read(SKILL_PATH)
    debug = read(SKILL_DIR / "references" / "run-and-debug.md")
    text = skill + debug

    for concept in (
        "PASS",
        "NONE",
        "FAIL",
        "APPLICATION",
        "BLOCKED",
        "AUTH",
        "ENVIRONMENT",
        "SAFETY",
        "PRECONDITION",
        "UNVERIFIED",
        "TEST",
        "BLOCKED/ENVIRONMENT",
        "BLOCKED/PRECONDITION",
        "BLOCKED/SAFETY",
        "UNVERIFIED/TEST",
    ):
        assert concept in text
    assert re.search(r"`PASS`\s*\|\s*`NONE`", skill)
    assert re.search(r"`FAIL`\s*\|\s*`APPLICATION`", skill)
    assert re.search(r"`UNVERIFIED`\s*\|\s*`NONE`.*`TEST`", skill)
    assert re.search(r"Исправь минимально и повтори тот же\s+targeted test", debug)
    assert "не ослабляй assertion" in debug
    assert "Общий `PASS/NONE`" in skill
    assert "а не «багов нет»" in skill


def test_public_skill_has_no_pilot_or_local_repository_dependency() -> None:
    text = all_public_text()
    forbidden_fragments = (
        "testapp-skills-",
        "TestApp",
        "Тестовое приложение",
        "Заказы клиентов",
        "Остатки товаров",
        "Самопроверка",
        "app-669400117",
        "1.0-244",
        "f179ab1e",
        "/Users/",
        "tools/",
        ".claude/skills",
    )

    folded_text = text.casefold()
    for fragment in forbidden_fragments:
        assert fragment.casefold() not in folded_text


def test_repository_documents_runtime_and_discovers_skill() -> None:
    readme = read(ROOT_DIR / "README.md")
    claude = read(ROOT_DIR / "CLAUDE.md")

    assert "skills/xbsl-playwright/SKILL.md" in readme
    assert "`Node.js` и `@playwright/test`" in readme
    assert "Node-зависимости не устанавливаются" in readme
    assert "Создай Playwright smoke-тест" in readme
    assert "xbsl-playwright/" in claude
    assert "не выполняет deploy/cloud API" in claude
    assert "skill-creator/quick_validate.py" in claude
    assert "legacy-ключ `compatibility`" in claude
    assert not (ROOT_DIR / "package.json").exists()
    assert not (ROOT_DIR / "node_modules").exists()
