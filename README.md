# XBSL Skills — AI-инструменты для 1С:Элемент

[![Docs](https://img.shields.io/badge/docs-github_pages-108679?style=flat-square)](https://korolevpavel.github.io/xbsl-ai-skills/)
[![License](https://img.shields.io/badge/license-MIT-d68048?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.x-2f6b94?style=flat-square)](#требования)



Набор скиллов для работы с проектами на платформе **1С:Элемент (XBSL)**.

Скиллы совместимы с [Claude Code](https://claude.ai/code) и другими AI-агентами, поддерживающими формат скиллов.

## Видео

Запись живого созвона: подключаем Claude Code и Codex к проекту на 1С:Элемент, работаем со скиллами, создаём объекты конфигурации и доводим всё до деплоя в 1CmyCloud.

[![YouTube](https://img.shields.io/badge/YouTube-FF0000?logo=youtube&logoColor=white)](https://youtu.be/kWJOAJ5-6EY)
[![ВКонтакте](https://img.shields.io/badge/ВКонтакте-0077FF?logo=vk&logoColor=white)](https://vk.com/video-232435421_456239040)

## Скиллы

| Скилл | Описание |
|-------|----------|
| [`xbsl-uuid`](.claude/skills/xbsl-uuid/SKILL.md) | Генерация UUID v4 для объектов конфигурации |
| [`xbsl-init`](.claude/skills/xbsl-init/SKILL.md) | Инициализация нового проекта: создаёт Проект.yaml, Проект.xbsl и Подсистема.yaml в правильном формате |
| [`xbsl-explore`](.claude/skills/xbsl-explore/SKILL.md) | Разведка структуры проекта: находит проекты, подсистемы, объекты, проверяет конфликты имён |
| [`xbsl-meta-add`](.claude/skills/xbsl-meta-add/SKILL.md) | Создание объекта конфигурации (Справочник, Документ, Перечисление и др.) по описанию |
| [`xbsl-form-add`](.claude/skills/xbsl-form-add/SKILL.md) | Создание формы интерфейса (ФормаОбъекта и/или ФормаСписка) для объекта конфигурации |
| [`xbsl-deploy`](.claude/skills/xbsl-deploy/SKILL.md) | Управление приложениями на 1С:Предприятие.Элемент: деплой, запуск, остановка, статус, merge |
| [`xbsl-pattern-register`](.claude/skills/xbsl-pattern-register/SKILL.md) | Движения по регистру накопления (приход, расход, обороты, контроль остатков) и регистру сведений (запись, удаление, срез последних) |

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
- `python3` — для работы скиллов `xbsl-explore`, `xbsl-uuid`, `xbsl-form-add`, `xbsl-deploy` и `xbsl-pattern-register`

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

```
Добавь движения документа РасходнаяНакладная в регистр ТоварыНаСкладах
```

## Структура проекта 1С:Элемент

Скиллы ориентируются на стандартную структуру проекта:

```
<корень>/
    <Поставщик>/
        <Проект>/
            Проект.yaml
            Проект.xbsl     # обработчики НастройкаПриложения / ОбновлениеПроекта
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
pytest tests/skills/xbsl_pattern_register/

# Покрытие кода
coverage run -m pytest && coverage report
```

## GitHub Pages

Сайт собирается автоматически через GitHub Actions из `README.md` и файлов `.claude/skills/*/SKILL.md`.

Локальная сборка:

```bash
pip install -r requirements-site.txt
python scripts/build_site.py
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
