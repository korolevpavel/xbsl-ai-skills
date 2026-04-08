---
name: xbsl-form-info
description: >
  Анализ объекта конфигурации 1С:Элемент: возвращает object_path, fields, tc, namespace,
  suggested_layout, existing_forms. Используется скиллами xbsl-form-add и xbsl-file-add
  перед созданием или изменением форм и реквизитов. Вызывай этот скилл всякий раз,
  когда нужно узнать структуру объекта (реквизиты, ТЧ, пространство имён, существующие формы)
  перед добавлением компонентов интерфейса или реквизитов-вложений.
compatibility:
  runtime:
    - python3
---

## Назначение

Запускает `scripts/form_info.py` и возвращает JSON-структуру с данными об объекте конфигурации.

## Команда

```bash
python3 .claude/skills/xbsl-form-info/scripts/form_info.py --name <ИмяОбъекта> --root .
```

## Возвращает JSON

```json
{
  "object_path": "/path/to/subsystem",
  "object_file": "Сотрудники.yaml",
  "object_type": "Справочник",
  "namespace": "vendor::project::subsystem",
  "field_count": 7,
  "tc_count": 1,
  "fields": [{"name": "Имя", "type": "Строка"}],
  "tc": [{"name": "Навыки"}],
  "suggested_layout": "panels",
  "existing_forms": {
    "ФормаОбъекта": "СотрудникиФормаОбъекта.yaml",
    "ФормаСписка": null
  },
  "is_hierarchical": false,
  "additional_hierarchies": [],
  "report_params": [],
  "data_source_kind": null,
  "data_source": null
}
```

## Варианты suggested_layout

| Значение | Условие |
|----------|---------|
| `simple` | нет табличных частей |
| `panels` | 1 ТЧ и 5+ реквизитов |
| `tabs` | 2+ ТЧ или <5 реквизитов |
| `report` | объект типа Отчет |

## Обработка ошибок

- Объект не найден: `{"error": "...", "searched_in": "..."}`
- Найдено несколько объектов: `{"error": "...", "matches": [...]}`
