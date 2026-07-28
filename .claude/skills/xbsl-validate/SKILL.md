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

Используй CLI:

```bash
{python} .claude/skills/xbsl-validate/scripts/validate.py PATH... [--format text|json]
```

Гарантии:

- только читает входные файлы и каталоги;
- рекурсивно обходит каталоги и проверяет только `*.yaml`;
- выдаёт детерминированные diagnostics в `text` или едином JSON envelope;
- использует `.claude/skills/xbsl-meta-add/object-coverage.json` как
  единственный registry типов, статусов и владельцев;
- использует `.claude/skills/xbsl-meta-add/references/types.md` как источник
  grammar для `Тип`.

Коды завершения:

- `0` — ошибок нет; warning diagnostics допустимы;
- `1` — contract violations;
- `2` — ошибка аргументов, I/O или parser failure.

`object-coverage.json` не является JSON Schema. Для `partial` объектов CLI
сообщает `coverage.partial`, для `routed` вызывает adapter owning skill, а
`automatic`/`out_of_scope` остаются warning diagnostics.
