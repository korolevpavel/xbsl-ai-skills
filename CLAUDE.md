# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Назначение репозитория

Набор скиллов для AI-агентов, работающих с проектами на платформе **1С:Элемент (XBSL/SBSL)** — язык со статической типизацией для разработки бизнес-приложений.

## Структура репозитория

```
.claude/skills/          # скиллы Claude Code
    xbsl-uuid/           # генерация UUID v4
    xbsl-explore/        # разведка структуры проекта
        scripts/explore.py
    xbsl-meta-add/       # создание объектов конфигурации
        references/      # спецификации по типам объектов (один .md на тип)
    xbsl-form-add/       # создание форм интерфейса (КомпонентИнтерфейса)
        references/      # спецификации ФормаОбъекта, ФормаСписка, elements
    xbsl-deploy/         # деплой на 1С:Предприятие.Элемент
        scripts/api.py   # HTTP-клиент Console API v2
        references/endpoints.md
    xbsl-pattern-register/  # паттерн движений по регистру накопления и сведений
        scripts/extract_meta.py   # извлекает поля РН, РС и Документа из YAML
        references/движения-рн.md # шаблоны кода паттернов A1–A5, B (РегистрНакопления)
        references/движения-рс.md # шаблоны кода паттернов C1–C4 (РегистрСведений)
        references/теория.md      # механика платформы
tools/                   # материалы и инструменты (в .gitignore)
```

## Скиллы

### xbsl-uuid
Генерирует N UUID v4 через `python3 -c`. Вызывается другими скиллами — не напрямую пользователем.

### xbsl-explore
Запускает `scripts/explore.py --type {Тип} --name {Имя} --root {root}`. Возвращает JSON с `suggested_path` (куда класть новый файл) и `conflict` (существующий объект с таким именем). **Вызывается перед созданием любого объекта.**

### xbsl-meta-add
Создаёт объект конфигурации (`.yaml` + опционально `.xbsl`). Оркестрирует xbsl-explore и xbsl-uuid. Читает спецификацию из `references/{ТипОбъекта}.md`. Поддерживаемые типы: Перечисление, Справочник, Документ, РегистрСведений, РегистрНакопления, ОбщийМодуль, Структура, ЛокализованныеСтроки, HttpСервис, ГлобальноеКлиентскоеСобытие, КлючДоступа.

### xbsl-deploy
Управляет приложениями на платформе 1С:Предприятие.Элемент через Console API v2. `scripts/api.py` — самодостаточный HTTP-клиент (только stdlib Python). Конфигурируется через env vars: `ELEMENT_BASE_URL`, `ELEMENT_CLIENT_ID`, `ELEMENT_CLIENT_SECRET` (обязательные), `ELEMENT_APP_ID`, `ELEMENT_PROJECT_ID`, `ELEMENT_BRANCH`, `ELEMENT_SPACE_ID` (опциональные).

### xbsl-form-add
Создаёт форму интерфейса (`КомпонентИнтерфейса`) — `ФормаОбъекта` и/или `ФормаСписка`. Оркестрирует xbsl-explore и xbsl-uuid. Читает спецификацию из `references/ФормаОбъекта.md` или `references/ФормаСписка.md`. `scripts/form_info.py` — анализирует объект конфигурации и возвращает JSON с `object_path`, `fields`, `tc`, `namespace`, `suggested_layout`, `existing_forms`.

### xbsl-pattern-register
Реализует движения по регистру накопления и регистру сведений в `.xbsl`. Не создаёт объекты — только пишет код обработчика. Алгоритм: запустить `scripts/extract_meta.py` для регистра и документа → выбрать паттерн → дополнить существующий `.xbsl` файл. Паттерны РН: A1 (приход), A2 (расход), A3 (обороты), A4 (отмена проведения), A5 (два регистра), B (контроль остатков). Паттерны РС: C1 (запись/обновление), C2 (добавить без замены), C3 (удалить по фильтру), C4 (срез последних).

## Структура проекта 1С:Элемент

Проекты 1С:Элемент, с которыми работают скиллы, устроены так:
```
<корень>/
    <Проект>/
        Проект.yaml
        <Подсистема>/
            Подсистема.yaml
            СтатусЗадачи.yaml     # объект метаданных
            СтатусЗадачи.xbsl     # методы объекта (опционально)
```

`explore.py` определяет проекты по наличию `Проект.yaml`, подсистемы — по `Подсистема.yaml`.

## Команды разработки

```bash
# Запустить все тесты
pytest

# Запустить тесты одного скилла
pytest tests/skills/xbsl_deploy/
pytest tests/skills/xbsl_explore/
pytest tests/skills/xbsl_form_add/
pytest tests/skills/xbsl_pattern_register/

# Запустить один тестовый файл
pytest tests/skills/xbsl_deploy/test_api.py

# Покрытие кода (только xbsl-deploy и xbsl-form-add)
coverage run -m pytest && coverage report

# Установить dev-зависимости (pytest, coverage)
pip install -r requirements-dev.txt
```

Виртуальное окружение: `.venv/`, менеджер зависимостей — `uv` (`uv.lock`).

## Разработка скиллов

Каждый скилл — папка в `.claude/skills/` с обязательным файлом `SKILL.md`. Frontmatter:
```yaml
---
name: имя-скилла        # совпадает с именем папки, a-z0-9-
description: >          # что делает + когда вызывать (до 1024 символов)
  ...
compatibility:          # опционально
  runtime:
    - python3
---
```

Ресурсы скилла (`references/`, `scripts/`) ссылаются из SKILL.md относительными путями (`references/foo.md`), но в bash-командах используется полный путь от корня проекта (`.claude/skills/<имя>/scripts/foo.py`).

При разработке нового скилла для 1С:Элемент — ориентируйся на существующие скиллы как образец.
