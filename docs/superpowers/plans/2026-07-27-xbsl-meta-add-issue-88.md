# xbsl-meta-add 9.2 Contract Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the existing `xbsl-meta-add` contracts tracked by GitHub issue #88 so that generated metadata and XBSL examples match the documented 1С:Элемент 9.2 behavior.

**Architecture:** Keep `references/` as the human-readable source of generation rules, enforce executable behavior in the existing HTTP generator, and add narrow regression tests around canonical artifacts and forbidden legacy patterns. Do not build the general metadata validator planned in issue #8; cross-file report checks remain test-only until that dependency lands.

**Tech Stack:** Markdown skill contracts, Python 3.10 standard library, pytest, YAML/XBQL/XBSL fixture text.

## Global Constraints

- Treat `xbsl-docs` 9.1 schemas as the baseline and the official 1С:Элемент 9.2 change log as the delta.
- Label all corrected behavior as valid for 1С:Элемент 9.2; do not claim that every `latest` MCP page is a separate 9.2 schema.
- Keep the public HTTP route as `/<resource>` because the platform adds `/api/`; reject the legacy `/api` prefix instead of silently emitting `/api/api/...`.
- Do not emit `КонтрольДоступа` unless the caller explicitly supplies `--access`.
- Keep report properties `ВключатьВАвтоИнтерфейс` and `Форма` at the report root, not under `Интерфейс`.
- Require exact set equality between `.xbql` parameters and report `ПараметрыЗапроса`.
- Use Russian accumulation-register virtual fields `<Ресурс>Оборот`, `<Ресурс>Приход`, and `<Ресурс>Расход`.
- Every information-register dimension participates in the record key; `Ведущее` controls delete cascading for a referenced object and does not define the key.
- Allow `НезаполненноеЗначение` for the catalog system field `Наименование`; for developer fields document it only for `Тип: Строка`.
- Do not advertise generic `Уникальность`; document uniqueness only on system fields whose own contract supports it.
- Emit `Представление` only when it names a field declared by the same object.
- Catalog UUID accounting includes the object, developer fields, table parts and their fields, additional hierarchies, and lock spaces; document UUID accounting includes the object, developer fields, table parts and their fields, and lock spaces.
- Use global-event methods `<Событие>.Оповестить(...)` and `<Событие>.ПодключитьОбработчик(...)`.
- Use direct localized-string calls in XBSL without the YAML-only `$` prefix.
- The standard access-key owner parameter is exactly `Имя: Владелец` plus `Тип`, without `Ид`; developer parameters contain `Ид`, `Имя`, and `Тип`.
- Do not use undocumented `Доступ.ПроверитьКлюч`; direct entity access through documented access-resolution handlers and documented permission APIs.
- Do not add third-party runtime dependencies.
- All Codex-authored commits must contain `Co-Authored-By: codex <codex@openai.com>`.

---

### Task 1: Reject legacy HTTP roots and align the skill command

**Files:**
- Modify: `skills/xbsl-meta-add/scripts/generate_http.py`
- Modify: `skills/xbsl-meta-add/SKILL.md`
- Modify: `skills/xbsl-meta-add/references/HttpСервис.md`
- Modify: `tests/skills/xbsl_meta_add/test_generate_http.py`

**Interfaces:**
- Consumes: existing `build_yaml(name, url, access, templates)` and `main(argv=None)` behavior.
- Produces: `validate_root_url(url: str) -> str`, returning a valid root unchanged and raising `ValueError` for `api`, `/api`, and `/api/...`.

- [ ] **Step 1: Add RED tests for the valid root, forbidden legacy prefix, dry-run validation, and explicit access**

Import `validate_root_url`. Change all positive HTTP examples from `/api/test`, `/api/mine`, `/api/sales`, and `/api/x` to `/test`, `/mine`, `/sales`, and `/x`. Add these focused tests:

```python
@pytest.mark.parametrize("url", ["api", "/api", "/api/orders"])
def test_validate_root_url_rejects_platform_api_prefix(url):
    with pytest.raises(ValueError, match="Платформа автоматически добавляет /api/"):
        validate_root_url(url)


def test_validate_root_url_accepts_resource_root():
    assert validate_root_url("/orders") == "/orders"


def test_main_rejects_legacy_root_even_in_dry_run(tmp_path, capsys):
    with pytest.raises(SystemExit):
        main([
            "--name", "Orders",
            "--url", "/api/orders",
            "--routes", "GET /",
            "--root", str(tmp_path),
        ])
    assert "Платформа автоматически добавляет /api/" in capsys.readouterr().err
```

Keep the existing `test_no_access_block_when_none` assertion and make the primary `build_yaml` test assert `КорневойUrl: /test`.

- [ ] **Step 2: Run the focused tests and observe RED**

Run:

```bash
.venv/bin/pytest tests/skills/xbsl_meta_add/test_generate_http.py -q
```

Expected: collection or assertion failure because `validate_root_url` does not exist and legacy roots are accepted.

- [ ] **Step 3: Implement one root validator and call it before dry-run/apply branching**

Add this standard-library-only function near route parsing:

```python
def validate_root_url(url: str) -> str:
    normalized = url.strip()
    first_segment = normalized.lstrip("/").split("/", 1)[0].lower()
    if first_segment == "api":
        raise ValueError(
            "КорневойUrl не должен начинаться с /api: "
            "платформа автоматически добавляет /api/"
        )
    if not normalized.startswith("/"):
        raise ValueError("КорневойUrl должен начинаться с /")
    return normalized
```

Call it once in the create flow before printing the dry-run or writing files. Convert its `ValueError` into the generator's existing CLI error form so both dry-run and `--apply` exit non-zero with the diagnostic on stderr. Pass the validated value to `build_yaml`.

- [ ] **Step 4: Align instructions and reference examples**

In `SKILL.md`, use:

```bash
{python} skills/xbsl-meta-add/scripts/generate_http.py \
  --name <ИмяСервиса> \
  --url /<ресурс> \
  --routes "GET /, POST /, GET /{id}, PUT /{id}, DELETE /{id}" \
  --root <корень_проекта> \
  --apply
```

State that `/api` is reserved and rejected, and that omitting `--access` omits the access block. In `HttpСервис.md`, retain the `/<ресурс>` contract and add the same rejection rule without changing the current explicit-access semantics.

- [ ] **Step 5: Run RED tests to GREEN and the complete suite**

Run:

```bash
.venv/bin/pytest tests/skills/xbsl_meta_add/test_generate_http.py -q
.venv/bin/pytest -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the independently testable HTTP correction**

```bash
git add skills/xbsl-meta-add/SKILL.md \
  skills/xbsl-meta-add/references/HttpСервис.md \
  skills/xbsl-meta-add/scripts/generate_http.py \
  tests/skills/xbsl_meta_add/test_generate_http.py \
  docs/superpowers/plans/2026-07-27-xbsl-meta-add-issue-88.md
git commit -m "fix(xbsl-meta-add): correct HTTP service root contract" \
  -m "Co-Authored-By: codex <codex@openai.com>"
```

### Task 2: Make report metadata and XBQL a single checked contract

**Files:**
- Create: `skills/xbsl-meta-add/examples/ОтчетОборотыПродаж.yaml`
- Create: `skills/xbsl-meta-add/examples/ОтчетОборотыПродаж.xbql`
- Create: `tests/skills/xbsl_meta_add/test_reference_contracts.py`
- Modify: `skills/xbsl-meta-add/references/Отчет.md`
- Modify: `skills/xbsl-form-add/SKILL.md`
- Modify: `skills/xbsl-form-add/references/ФормаОтчета.md`

**Interfaces:**
- Consumes: a report YAML fixture whose `Запрос` points to the sibling `.xbql` filename.
- Produces: test-only helpers `top_level_keys(text: str) -> set[str]`, `report_parameter_names(text: str) -> set[str]`, and `xbql_parameter_names(text: str) -> set[str]`.

- [ ] **Step 1: Add canonical fixture files with one query parameter**

The YAML fixture must declare `ВключатьВАвтоИнтерфейс` and `Форма` without an `Интерфейс` parent, point `Запрос` to `ОтчетОборотыПродаж.xbql`, and define one parameter named `НачалоПериода`. The XBQL fixture must use `&НачалоПериода` and aggregate `СуммаОборот`; it must not contain `Turnover`.

- [ ] **Step 2: Add RED contract tests over the canonical fixture and current references**

Implement small indentation/token helpers in `test_reference_contracts.py` using only `pathlib.Path` and `re`. Assert:

```python
def test_report_root_properties_are_not_nested_under_interface():
    assert {"ВключатьВАвтоИнтерфейс", "Форма"} <= top_level_keys(REPORT_YAML)
    assert "Интерфейс:" not in REPORT_YAML


def test_report_and_xbql_parameter_sets_are_equal():
    assert report_parameter_names(REPORT_YAML) == xbql_parameter_names(REPORT_XBQL)
    assert report_parameter_names(REPORT_YAML) == {"НачалоПериода"}


def test_accumulation_virtual_fields_use_russian_suffixes():
    report_reference = read_reference("Отчет.md")
    for suffix in ("Оборот", "Приход", "Расход"):
        assert f"<ИмяРесурса>{suffix}" in report_reference
    assert "Turnover" not in report_reference
    assert "Turnover" not in REPORT_XBQL
```

Also assert that the report reference and both `xbsl-form-add` consumers show `ВключатьВАвтоИнтерфейс` and `Форма` as top-level keys in their report-object examples.

- [ ] **Step 3: Run report tests and observe RED**

Run:

```bash
.venv/bin/pytest tests/skills/xbsl_meta_add/test_reference_contracts.py -k report -q
```

Expected: failures from missing fixtures and the old nested/English-suffix contracts.

- [ ] **Step 4: Correct the report reference and both form-skill consumers**

Document all of the following in `Отчет.md`:

```yaml
ВключатьВАвтоИнтерфейс: Истина
Форма: ФормаОтчета
```

Use a sibling query:

```yaml
ВидИсточникаДанных: Запрос
Запрос: ОтчетОборотыПродаж.xbql
```

State the exact invariant:

```text
set(имена &параметров в XBQL) == set(имена элементов ПараметрыЗапроса)
```

Replace the virtual-resource table with `<ИмяРесурса>Оборот`, `<ИмяРесурса>Приход`, and `<ИмяРесурса>Расход`. Correct the report-object mutation examples in `xbsl-form-add/SKILL.md` and `references/ФормаОтчета.md` so neither creates an `Интерфейс` wrapper.

- [ ] **Step 5: Run report tests to GREEN and the complete suite**

Run:

```bash
.venv/bin/pytest tests/skills/xbsl_meta_add/test_reference_contracts.py -k report -q
.venv/bin/pytest -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the independently testable report correction**

```bash
git add skills/xbsl-meta-add/examples \
  skills/xbsl-meta-add/references/Отчет.md \
  skills/xbsl-form-add/SKILL.md \
  skills/xbsl-form-add/references/ФормаОтчета.md \
  tests/skills/xbsl_meta_add/test_reference_contracts.py
git commit -m "fix(xbsl-meta-add): align report metadata and XBQL" \
  -m "Co-Authored-By: codex <codex@openai.com>"
```

### Task 3: Correct field semantics, presentation references, and UUID accounting

**Files:**
- Modify: `skills/xbsl-meta-add/references/types.md`
- Modify: `skills/xbsl-meta-add/references/РегистрСведений.md`
- Modify: `skills/xbsl-meta-add/references/РегистрНакопления.md`
- Modify: `skills/xbsl-meta-add/references/Справочник.md`
- Modify: `skills/xbsl-meta-add/references/Документ.md`
- Modify: `skills/xbsl-meta-add/references/ТабличныеЧасти.md`
- Modify: `tests/skills/xbsl_meta_add/test_reference_contracts.py`

**Interfaces:**
- Consumes: `read_reference(name: str) -> str` from Task 2.
- Produces: stable metadata rules enforced against the reference set; no production validator is introduced.

- [ ] **Step 1: Add RED tests for each documented metadata regression**

Add focused tests that assert:

```python
def test_information_register_key_and_leading_dimension_are_distinct():
    text = read_reference("РегистрСведений.md")
    assert "Все измерения образуют ключ записи" in text
    assert "каскад" in text.lower()
    assert "минимум одно измерение должно быть ведущим" not in text.lower()
    assert "ведущие измерения образуют первичный ключ" not in text.lower()


def test_generic_field_contract_does_not_advertise_uniqueness():
    assert "`Уникальность`" not in read_reference("types.md")


def test_catalog_name_can_define_empty_value_policy():
    text = read_reference("Справочник.md")
    assert "Наименование" in text
    assert "НезаполненноеЗначение: Разрешить" in text


def test_presentation_examples_reference_declared_fields():
    assert "Представление: ФИО" not in read_reference("Справочник.md")
    assert "Представление: Наименование" not in read_reference("Документ.md")


def test_uuid_contract_counts_hierarchies_and_lock_spaces():
    catalog = read_reference("Справочник.md")
    document = read_reference("Документ.md")
    assert "ДополнительныеИерархии" in catalog
    assert "ПространстваБлокировок" in catalog
    assert "ПространстваБлокировок" in document
```

Add a parametrized test over `types.md`, `РегистрСведений.md`, `РегистрНакопления.md`, `Документ.md`, and `ТабличныеЧасти.md` that rejects examples where a non-string developer field combines `Тип: <...>.Ссылка` with `НезаполненноеЗначение`.

- [ ] **Step 2: Run metadata tests and observe RED**

Run:

```bash
.venv/bin/pytest tests/skills/xbsl_meta_add/test_reference_contracts.py -k "information_register or generic_field or catalog_name or presentation or uuid or empty_value" -q
```

Expected: failures for the current key, uniqueness, presentation, UUID, and empty-value guidance.

- [ ] **Step 3: Correct information-register and generic field rules**

In `РегистрСведений.md`, state that every dimension participates in the record key and period also participates for a periodic register. Define `Ведущее` as delete cascading for a referenced database object and remove both the minimum-one requirement and key semantics.

In `types.md`, remove generic `Уникальность`, document `НезаполненноеЗначение` only for developer fields with `Тип: Строка`, and explicitly point catalog `Наименование` to its object-specific rule. Remove invalid `НезаполненноеЗначение` lines from reference-typed examples across the five affected references.

- [ ] **Step 4: Correct catalog/document presentation and UUID formulas**

Use a declared field in every `Представление` example or omit `Представление` to allow the platform default. For `Наименование`, document the accepted `НезаполненноеЗначение` values and show `Разрешить` only when an empty name is intentional.

Write the formulas explicitly:

```text
Справочник = объект + пользовательские реквизиты + табличные части
  + реквизиты табличных частей + дополнительные иерархии
  + пространства блокировок

Документ = объект + пользовательские реквизиты + табличные части
  + реквизиты табличных частей + пространства блокировок
```

Add compact YAML fragments for `ДополнительныеИерархии` and `ПространстваБлокировок`, each with its own UUID, and state that system fields excluded by the object schema do not consume generated UUIDs.

- [ ] **Step 5: Run metadata tests to GREEN and the complete suite**

Run:

```bash
.venv/bin/pytest tests/skills/xbsl_meta_add/test_reference_contracts.py -k "information_register or generic_field or catalog_name or presentation or uuid or empty_value" -q
.venv/bin/pytest -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the independently testable metadata correction**

```bash
git add skills/xbsl-meta-add/references \
  tests/skills/xbsl_meta_add/test_reference_contracts.py
git commit -m "fix(xbsl-meta-add): correct metadata field contracts" \
  -m "Co-Authored-By: codex <codex@openai.com>"
```

### Task 4: Replace obsolete XBSL APIs and correct access-key parameters

**Files:**
- Modify: `skills/xbsl-meta-add/references/ГлобальноеКлиентскоеСобытие.md`
- Modify: `skills/xbsl-meta-add/references/ЛокализованныеСтроки.md`
- Modify: `skills/xbsl-meta-add/references/КлючДоступа.md`
- Modify: `tests/skills/xbsl_meta_add/test_reference_contracts.py`
- Modify: `tests/test_xbsl_spec_contract.py`

**Interfaces:**
- Consumes: Markdown `xbsl` code-block extraction from `tests/test_xbsl_spec_contract.py` and `read_reference` from Task 2.
- Produces: documented 9.2 XBSL examples with no obsolete global-event, localization, or access-check calls.

- [ ] **Step 1: Add RED tests for documented API calls and access-key shapes**

Extend the XBSL contract test to reject these tokens in every `xbsl-meta-add` XBSL block:

```python
OBSOLETE_META_ADD_APIS = (
    "Приложение.ВызватьГлобальноеКлиентскоеСобытие",
    "ФоматСтроки",
    "Доступ.ПроверитьКлюч",
)
```

Add reference tests asserting that:

```python
def test_global_event_uses_documented_instance_methods():
    text = read_reference("ГлобальноеКлиентскоеСобытие.md")
    assert ".Оповестить(" in text
    assert ".ПодключитьОбработчик(" in text


def test_localized_strings_use_direct_xbsl_access():
    text = read_reference("ЛокализованныеСтроки.md")
    xbsl = "\n".join(xbsl_code_blocks(text))
    assert "$ЛокализованныеСтроки" not in xbsl
    assert "ЛокализованныеСтроки.ЗаказСохранён" in xbsl


def test_access_key_owner_and_developer_parameters_have_distinct_shapes():
    text = read_reference("КлючДоступа.md")
    assert "Имя: Владелец" in text
    assert "системный параметр `Владелец` не содержит `Ид`" in text
    assert "пользовательский параметр содержит `Ид`, `Имя` и `Тип`" in text
    assert "Доступ.ПроверитьКлюч" not in text
```

Import or share the existing `xbsl_code_blocks` helper instead of parsing prose as executable XBSL.

- [ ] **Step 2: Run API tests and observe RED**

Run:

```bash
.venv/bin/pytest tests/skills/xbsl_meta_add/test_reference_contracts.py -k "global_event or localized_strings or access_key" -q
.venv/bin/pytest tests/test_xbsl_spec_contract.py -q
```

Expected: failures on the obsolete API examples.

- [ ] **Step 3: Rewrite global-event and localization examples**

Show an event announcement as:

```xbsl
ЗаказИзменён.Оповестить(Заказ.Ссылка)
```

Show subscription as:

```xbsl
ЗаказИзменён.ПодключитьОбработчик(&ОбработатьИзменениеЗаказа)
```

State that the handler parameter list must exactly match the event parameters. Keep `$ЛокализованныеСтроки.<Имя>` only in YAML property values; in XBSL show:

```xbsl
знч Сообщение = ЛокализованныеСтроки.ЗаказСохранён
знч СНомером = ЛокализованныеСтроки.СозданЗаказНомер(НомерЗаказа)
```

- [ ] **Step 4: Rewrite access-key parameter and permission guidance**

Keep the owner YAML shape:

```yaml
Параметры:
  -
    Имя: Владелец
    Тип: Сотрудники.Ссылка?
```

Show a separate developer parameter with `Ид`, `Имя`, and `Тип`. Remove `Доступ.ПроверитьКлюч` entirely. Explain that entity access is implemented through `РазрешениеДоступа` handlers and that general rights are checked only with documented `КонтрольДоступа.ЕстьПраво(...)` or `КонтрольДоступа.ПроверитьПраво(...)` APIs when that is the actual requirement.

- [ ] **Step 5: Run API tests to GREEN and the complete suite**

Run:

```bash
.venv/bin/pytest tests/skills/xbsl_meta_add/test_reference_contracts.py -k "global_event or localized_strings or access_key" -q
.venv/bin/pytest tests/test_xbsl_spec_contract.py -q
.venv/bin/pytest -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the independently testable API correction**

```bash
git add skills/xbsl-meta-add/references \
  tests/skills/xbsl_meta_add/test_reference_contracts.py \
  tests/test_xbsl_spec_contract.py
git commit -m "fix(xbsl-meta-add): update documented XBSL APIs" \
  -m "Co-Authored-By: codex <codex@openai.com>"
```

### Task 5: Pressure-test the edited skill and verify the branch

**Files:**
- Inspect: all files changed by Tasks 1–4
- Test: `tests/skills/xbsl_meta_add/test_generate_http.py`
- Test: `tests/skills/xbsl_meta_add/test_reference_contracts.py`
- Test: `tests/test_xbsl_spec_contract.py`

**Interfaces:**
- Consumes: complete corrected skill and all regression tests.
- Produces: post-change application reports demonstrating that representative agents no longer reproduce the six baseline failures.

- [ ] **Step 1: Run three fresh application scenarios**

Dispatch fresh read-only agents against the edited worktree:

1. Generate an HTTP service and turnover report from the skill, then report root URL, access block, report root properties, XBQL resource names, and parameter-set equality.
2. Generate catalog, document, and information-register snippets, then report `Ведущее`, empty-value, uniqueness, presentation, and UUID decisions.
3. Generate global-event, localization, and access-key snippets, then report every XBSL API and the owner/developer parameter shapes.

Each report must quote only short generated fragments and mark every Global Constraint as pass or fail.

- [ ] **Step 2: Correct any pressure-test regression with a failing automated test first**

For each failed constraint, add the narrowest test to one of the three listed test files, run that test to confirm RED, correct the relevant reference/generator, and rerun it to GREEN. Do not widen scope to new object types assigned to issues #89–#93.

- [ ] **Step 3: Run fresh verification**

Run:

```bash
.venv/bin/pytest tests/skills/xbsl_meta_add/test_generate_http.py -q
.venv/bin/pytest tests/skills/xbsl_meta_add/test_reference_contracts.py -q
.venv/bin/pytest tests/test_xbsl_spec_contract.py -q
.venv/bin/pytest -q
git diff --check origin/master...HEAD
git status --short
```

Expected: focused and full tests pass, `git diff --check` is empty, and only intentional branch changes are present.

- [ ] **Step 4: Commit pressure-test fixes only if Step 2 changed files**

```bash
git add skills tests
git commit -m "test(xbsl-meta-add): cover 9.2 contract regressions" \
  -m "Co-Authored-By: codex <codex@openai.com>"
```
