---
name: xbsl-validate
description: >
  Read-only validation for 1С:Предприятие.Элемент YAML metadata files. Use when
  Codex needs to check project `.yaml` files, fixture trees, examples, or
  generated artifacts against xbsl-meta-add coverage, common invariants, and
  type grammar without running 1С or modifying inputs.
---

# xbsl-validate

Во всех командах ниже `{python}` означает `python` в Windows и `python3` в macOS/Linux/WSL. Выбирай команду сразу по текущей ОС, не запускай оба варианта.

Используй CLI из текущего корня `skills`:

```bash
{python} <skills-root>/xbsl-validate/scripts/validate.py PATH... [--format text|json]
```

В исходниках репозитория это обычно
`skills/xbsl-validate/scripts/validate.py`, в установленном Codex
layout — `~/.codex/skills/xbsl-validate/scripts/validate.py`.

Гарантии:

- только читает входные файлы и каталоги;
- рекурсивно обходит каталоги и проверяет только `*.yaml`;
- выдаёт детерминированные diagnostics в `text` или едином JSON envelope;
- использует sibling skill `xbsl-meta-add/object-coverage.json` из того же
  корня `skills` как единственный registry типов, статусов и владельцев;
- использует `xbsl-meta-add/references/types.md` как источник grammar для
  `Тип`;
- сначала определяет owning schema; common-поля и grammar `Тип` проверяет
  только у функциональных объектов и только в их документированных type slots,
  а UI, `Проект.yaml` и `Подсистема.yaml` маршрутизирует без объектных
  false-positive diagnostics;
- для `Отчет`, `РегистрНакопления`, `РегистрСведений`, `КлючДоступа` и
  `ЗапланированноеЗадание` запускает object-specific validators после common
  слоя.

Стабильные object-specific rule ID:

- отчет: `owner.report.source`, `owner.report.query_companion`,
  `owner.report.query_parameters`, `owner.report.interface`;
- регистр: `owner.register.dimensions`, `owner.register.resources`,
  `owner.register.member`, `owner.register.invalid_uuid`,
  `owner.register.resource_type`, `owner.register.registrar`,
  `owner.register.kind`;
- запланированное задание: `owner.scheduled_task.schedule`,
  `owner.scheduled_task.time_literal`, `owner.scheduled_task.location`,
  `owner.scheduled_task.yaml_handler`,
  `owner.scheduled_task.missing_companion`,
  `owner.scheduled_task.unreadable_companion`,
  `owner.scheduled_task.handler`.
- ключ доступа: `owner.access_key.boolean_literal`,
  `owner.access_key.parameter_uuid`, `owner.access_key.system_recalculation_mode`,
  `owner.access_key.manual_handler_ignored`.

Коды завершения:

- `0` — ошибок нет; warning diagnostics допустимы;
- `1` — contract violations;
- `2` — ошибка аргументов, I/O или parser failure.

`object-coverage.json` не является JSON Schema. Для `partial` объектов CLI
сообщает `coverage.partial`, для `routed` вызывает adapter owning skill, а
`automatic`/`out_of_scope` остаются warning diagnostics.
