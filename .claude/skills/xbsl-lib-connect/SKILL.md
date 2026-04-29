---
name: xbsl-lib-connect
description: >
  Подключение внешней библиотеки (.xlib) к проекту 1С:Элемент. Автоматизирует полный
  цикл: получить .xlib (из файла, папки с исходниками или GitHub/GitLab URL),
  загрузить в панель управления через Console API, попросить пользователя выпустить
  релиз, прописать зависимость в Проект.yaml и дать рекомендации по использованию типов
  библиотеки. Вызывай когда нужно подключить внешнюю библиотеку, использовать типы
  другого поставщика, или добавить зависимость к проекту. НЕ для: создания объектов
  конфигурации — используй xbsl-meta-add.
compatibility:
  runtime:
    - python3
---

# xbsl-lib-connect

Скилл подключает внешнюю библиотеку к проекту 1С:Элемент.

**Вспомогательный скрипт:** `.claude/skills/xbsl-lib-connect/scripts/lib_connect.py`
(actions: `inspect`, `find-xlib`, `patch-yaml`, `analyze`, `validate-version`, `cleanup`)

**Важно:** выпуск релиза библиотеки невозможно автоматизировать через API — только через
веб-панель управления. Скилл выполняет всё вокруг этого шага, а для самого релиза даёт
пошаговую инструкцию и ждёт номер версии от пользователя.

---

## Шаг 0 — Подключение к облаку

Вызови скилл `xbsl-deploy` через инструмент `Skill` (если он ещё не активен в сессии):
```
Skill("xbsl-deploy")
```

Следуй **Шагу 0** и **Шагу 2** из xbsl-deploy:
- Шаг 0: загрузить переменные окружения (`set -a && source .env 2>/dev/null; set +a`), проверить наличие `ELEMENT_BASE_URL`, `ELEMENT_CLIENT_ID`, `ELEMENT_CLIENT_SECRET`
- Шаг 2: получить токен (`api.py --action get-token`)

Продолжать только если токен получен успешно.

---

## Шаг 1 — Определить источник библиотеки

Из запроса пользователя определить один из трёх источников:

### A. GitHub/GitLab URL
```bash
TMP_DIR=$(mktemp -d /tmp/xlib_src_XXXXXX)
git clone --depth 1 <URL> "$TMP_DIR"
```

Найти `.xlib` в клоне:
```bash
python3 .claude/skills/xbsl-lib-connect/scripts/lib_connect.py \
    --action find-xlib --dir "$TMP_DIR"
```

- Массив содержит **1 элемент** → использовать его как `LIB_PATH`
- Массив содержит **>1 элемента** → показать список пользователю, попросить выбрать
- Массив **пустой** → проверить `Проект.yaml` в клоне на наличие `ВидПроекта: Библиотека`
  - Есть → собрать (Шаг 2А: сборка из исходников)
  - Нет → **ошибка**: "Репозиторий не содержит .xlib и не является проектом библиотеки"

### B. Локальный файл `.xlib`
Использовать путь напрямую: `LIB_PATH=<путь>`

### C. Локальная папка с исходниками
Сначала поискать `.xlib` в папке:
```bash
python3 .claude/skills/xbsl-lib-connect/scripts/lib_connect.py \
    --action find-xlib --dir <папка>
```
Если найдены → выбрать (как в п. A). Иначе — проверить `Проект.yaml` и собрать (Шаг 2А).

---

## Шаг 2А — Сборка .xlib из исходников (если нужна)

```bash
python3 .claude/skills/xbsl-deploy/scripts/build.py \
    --project-dir <путь_к_папке_с_Проект.yaml> \
    --output /tmp \
    --kind library
```

Флаг `--kind library` генерирует файл с расширением `.xlib` и `ProjectKind: Library`
в `Assembly.yaml`. Если `ВидПроекта: Библиотека` указан в `Проект.yaml` — `--kind`
можно не передавать, он определяется автоматически.

Результат: путь к собранному `.xlib` файлу → сохранить в `LIB_PATH`.

---

## Шаг 2 — Прочитать метаданные .xlib

```bash
python3 .claude/skills/xbsl-lib-connect/scripts/lib_connect.py \
    --action inspect --file "$LIB_PATH"
```

Из JSON-ответа извлечь и сохранить:
- `vendor` → `LIB_VENDOR`
- `name` → `LIB_NAME`
- `version` → `LIB_VERSION`
- `technology_version` → для Шага 3
- `project_kind` → если не `Library` — скрипт завершится с ошибкой

---

## Шаг 3 — Проверить совместимость версий технологии

Прочитать `Проект.yaml` целевого проекта:
```bash
grep "ВерсияТехнологии" <путь>/*/Проект.yaml
```

Если `technology_version` из Шага 2 не пустой и в `Проект.yaml` есть `ВерсияТехнологии`
— сравнить. При несовпадении предупредить пользователя и спросить — продолжить или нет.

---

## Шаг 4 — Проверить, не подключена ли уже

Использовать dry-run режим patch-yaml для проверки:
```bash
python3 .claude/skills/xbsl-lib-connect/scripts/lib_connect.py \
    --action patch-yaml \
    --project-yaml <путь>/Проект.yaml \
    --name "$LIB_NAME" --vendor "$LIB_VENDOR" --version "0.0.0" \
    --dry-run
```

Сравнить `before` и `after` в ответе: если в `before` уже есть блок с `$LIB_NAME` и
`$LIB_VENDOR` — сообщить текущую версию и предложить обновить или выйти.

---

## Шаг 5 — Загрузить .xlib в облако

Вызови скилл `xbsl-deploy` через инструмент `Skill` (если он ещё не активен в сессии):
```
Skill("xbsl-deploy", args="Создать проект из файла сборки")
```

Следуй **Сценарию H** из xbsl-deploy, передав `$LIB_PATH` как файл сборки:
- H2: определить `space-id` через `list-spaces`
- H3: загрузить через `upload-build --file "$LIB_PATH" --space-id <space-id>`

После успешного выполнения Сценария H сохранить `project-id` вернувшегося проекта
→ он понадобится для инструкции по выпуску релиза в Шаге 6.

---

## Шаг 6 — Попросить пользователя выпустить релиз

Вывести инструкцию:

> **Необходимо выпустить релиз библиотеки вручную в панели управления.**
>
> 1. Откройте панель управления: `{ELEMENT_BASE_URL}`
> 2. Перейдите на вкладку **Проекты** → найдите **{LIB_NAME}** (поставщик: {LIB_VENDOR})
> 3. Откройте вкладку **Релизы** → нажмите **+ Выпустить новый релиз**
> 4. Выберите только что загруженную сборку (версия: {LIB_VERSION})
> 5. Задайте номер версии релиза (например, `1.0.0`) — **без суффикса, без дефисов**
> 6. Нажмите **Выпустить релиз**
>
> После этого введите номер версии релиза:

Получить ввод пользователя → `RELEASE_VERSION`.

Проверить формат:
```bash
python3 .claude/skills/xbsl-lib-connect/scripts/lib_connect.py \
    --action validate-version --version "$RELEASE_VERSION"
```
При `valid: false` — сообщить ошибку и попросить ввести снова.

---

## Шаг 7 — Обновить Проект.yaml целевого проекта

Сначала показать план изменений (dry-run):
```bash
python3 .claude/skills/xbsl-lib-connect/scripts/lib_connect.py \
    --action patch-yaml \
    --project-yaml <путь>/Проект.yaml \
    --name "$LIB_NAME" --vendor "$LIB_VENDOR" --version "$RELEASE_VERSION" \
    --dry-run
```

Показать пользователю содержимое `after` из ответа. Получить подтверждение.

Применить:
```bash
python3 .claude/skills/xbsl-lib-connect/scripts/lib_connect.py \
    --action patch-yaml \
    --project-yaml <путь>/Проект.yaml \
    --name "$LIB_NAME" --vendor "$LIB_VENDOR" --version "$RELEASE_VERSION"
```

---

## Шаг 8 — Анализ библиотеки и рекомендации

```bash
python3 .claude/skills/xbsl-lib-connect/scripts/lib_connect.py \
    --action analyze --file "$LIB_PATH"
```

На основе JSON-ответа вывести пользователю:

**Подсистемы библиотеки:**
- `{LIB_VENDOR}::{LIB_NAME}::{subsystem.name}` — {subsystem.title}

**Доступные типы (ОбластьВидимости: Глобально):**
- `{type.name}` ({type.kind})

**Как использовать в коде:**

```yaml
# В Подсистема.yaml целевого проекта:
Использование:
    - {LIB_VENDOR}::{LIB_NAME}::{Подсистема}

# В объекте интерфейса (.yaml):
Импорт:
    - {LIB_VENDOR}::{LIB_NAME}::{Подсистема}
```

```
# В XBSL-коде — полное имя типа:
перем х: {LIB_VENDOR}::{LIB_NAME}::{Подсистема}::{ИмяТипа}
```

---

## Шаг 9 — Очистка и предложение пересборки

Удалить временные папки:
```bash
[ -n "$TMP_DIR" ] && python3 .claude/skills/xbsl-lib-connect/scripts/lib_connect.py \
    --action cleanup --dir "$TMP_DIR"
```

Если задана переменная `ELEMENT_APP_ID` — предложить пересобрать через `xbsl-deploy`
(сценарий I: деплой из исходников).

---

## Итог

```
✓ Библиотека {LIB_VENDOR}::{LIB_NAME} v{RELEASE_VERSION} подключена к проекту.
✓ Проект.yaml обновлён.

Следующий шаг: пересобрать приложение, чтобы изменения вступили в силу.
```
