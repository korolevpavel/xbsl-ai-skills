# XBSL Skills — AI-инструменты для 1С:Элемент

Набор скиллов для работы с проектами на платформе **1С:Элемент (XBSL)**.

Скиллы совместимы с [Claude Code](https://claude.ai/code) и другими AI-агентами, поддерживающими формат скиллов.

## Скиллы

| Скилл | Описание |
|-------|----------|
| [`xbsl-uuid`](.claude/skills/xbsl-uuid/SKILL.md) | Генерация UUID v4 для объектов конфигурации |
| [`xbsl-explore`](.claude/skills/xbsl-explore/SKILL.md) | Разведка структуры проекта: находит проекты, подсистемы, объекты, проверяет конфликты имён |
| [`xbsl-meta-add`](.claude/skills/xbsl-meta-add/SKILL.md) | Создание объекта конфигурации (Справочник, Документ, Перечисление и др.) по описанию |
| [`xbsl-form-add`](.claude/skills/xbsl-form-add/SKILL.md) | Создание формы интерфейса (ФормаОбъекта и/или ФормаСписка) для объекта конфигурации |
| [`xbsl-deploy`](.claude/skills/xbsl-deploy/SKILL.md) | Управление приложениями на 1С:Предприятие.Элемент: деплой, запуск, остановка, статус, merge |

Спецификации по каждому типу объекта метаданных и справочник типов реквизитов хранятся в [`.claude/skills/xbsl-meta-add/references/`](.claude/skills/xbsl-meta-add/references/):

| Файл | Тип объекта |
|------|-------------|
| [`Перечисление.md`](.claude/skills/xbsl-meta-add/references/Перечисление.md) | Фиксированный набор значений (статусы, виды, приоритеты) |
| [`Справочник.md`](.claude/skills/xbsl-meta-add/references/Справочник.md) | Хранилище записей (сотрудники, контрагенты, товары) |
| [`Документ.md`](.claude/skills/xbsl-meta-add/references/Документ.md) | Бизнес-событие с историей (заказы, накладные, акты) |
| [`РегистрСведений.md`](.claude/skills/xbsl-meta-add/references/РегистрСведений.md) | Срезы данных по измерениям (курсы валют, цены) |
| [`РегистрНакопления.md`](.claude/skills/xbsl-meta-add/references/РегистрНакопления.md) | Обороты или остатки (продажи, складские остатки) |
| [`ОбщийМодуль.md`](.claude/skills/xbsl-meta-add/references/ОбщийМодуль.md) | Переиспользуемый код (утилиты, сервисы) |
| [`Структура.md`](.claude/skills/xbsl-meta-add/references/Структура.md) | DTO / value object |
| [`HttpСервис.md`](.claude/skills/xbsl-meta-add/references/HttpСервис.md) | REST API (эндпоинты для внешних систем) |
| [`ГлобальноеКлиентскоеСобытие.md`](.claude/skills/xbsl-meta-add/references/ГлобальноеКлиентскоеСобытие.md) | Событие между подсистемами |
| [`КлючДоступа.md`](.claude/skills/xbsl-meta-add/references/КлючДоступа.md) | Маркер прав доступа |
| [`ЛокализованныеСтроки.md`](.claude/skills/xbsl-meta-add/references/ЛокализованныеСтроки.md) | Тексты интерфейса |
| [`ТабличныеЧасти.md`](.claude/skills/xbsl-meta-add/references/ТабличныеЧасти.md) | Вложенные строки в Справочнике и Документе |
| [`types.md`](.claude/skills/xbsl-meta-add/references/types.md) | Справочник типов реквизитов |

## Требования

- [Claude Code](https://claude.ai/code) или другой AI-агент, поддерживающий скиллы
- `python3` — для работы скиллов `xbsl-explore`, `xbsl-uuid`, `xbsl-form-add` и `xbsl-deploy`

## Установка

Клонируй репозиторий и скопируй скиллы в свой проект:

```bash
git clone https://github.com/korolevpavel/xbsl-ai-skills.git
mkdir -p /путь/к/твоему/проекту/.claude/skills/
cp -r xbsl-ai-skills/.claude/skills/ /путь/к/твоему/проекту/.claude/skills/
```

## Использование

Скиллы подхватываются автоматически. Просто опиши задачу в Claude Code:

```
Создай справочник Контрагенты с полями ИНН и КПП
```

```
Добавь перечисление статусов задачи: Новая, В работе, Завершена
```

```
Задеплой ветку main на Элемент
```

## Структура проекта 1С:Элемент

Скиллы ориентируются на стандартную структуру проекта:

```
<корень>/
    <Проект>/
        Проект.yaml
        <Подсистема>/
            Подсистема.yaml
            СтатусЗадачи.yaml     # объект метаданных
            СтатусЗадачи.xbsl     # методы объекта (опционально)
```

## Конфигурация xbsl-deploy

Создай файл `.env` в корне проекта:

```dotenv
# Обязательные
ELEMENT_BASE_URL=https://...
ELEMENT_CLIENT_ID=...
ELEMENT_CLIENT_SECRET=...

# Опциональные (экономят время на каждом деплое)
ELEMENT_APP_ID=...
ELEMENT_PROJECT_ID=...
ELEMENT_BRANCH=main
ELEMENT_SPACE_ID=...
```

## Разработка

```bash
# Установить зависимости
pip install -r requirements-dev.txt

# Запустить все тесты
pytest

# Тесты одного скилла
pytest tests/skills/xbsl_deploy/
pytest tests/skills/xbsl_explore/
pytest tests/skills/xbsl_form_add/

# Покрытие кода
coverage run -m pytest && coverage report
```

## Добавление новых скиллов

Каждый скилл — папка в `.claude/skills/` с файлом `SKILL.md`. Frontmatter:

```yaml
---
name: имя-скилла
description: >
  Описание для триггера скилла (по нему агент решает, когда вызывать)
---
```

Для создания и улучшения скиллов рекомендуется использовать [skill-creator](https://claude.com/plugins/skill-creator), а также руководствоваться рекомендациями [agentskills.io](https://agentskills.io).

## Лицензия

[MIT](LICENSE)
