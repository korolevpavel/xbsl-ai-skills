---
name: xbsl-deploy
description: >
  Используй этот скилл для любых операций с приложениями на платформе 1С:Предприятие.Элемент
  (1cmycloud.com): создать приложение, задеплоить ветку из внешнего git-репозитория (GitHub, GitLab и др.), обновить, проверить статус,
  запустить, остановить, удалить, принять изменения (merge). Вызывай скилл всякий раз, когда
  пользователь упоминает деплой, запуск, остановку или управление приложением на Элементе —
  даже если он не говорит явно "задеплой", а просто спрашивает "как дела с приложением" или
  "смёрджи ветку".
compatibility:
  runtime:
    - python3
---

# Деплой на 1С:Предприятие.Элемент

> Справочник по API: `references/endpoints.md` — читай его если нужны детали по полям запросов/ответов.

## Шаг 0: Загрузи переменные окружения

Перед любым обращением к API загрузи env vars. Выполни команду:

```bash
set -a && source .env 2>/dev/null; set +a
```

Если `.env` не найден — продолжай: нужные переменные могут быть уже заданы в системе.

Обязательные переменные: `ELEMENT_BASE_URL`, `ELEMENT_CLIENT_ID`, `ELEMENT_CLIENT_SECRET`.
Если хотя бы одна отсутствует — сообщи пользователю и остановись.

---

## Шаг 1: Определи намерение

| Фраза пользователя | Сценарий |
|---|---|
| создать / новое / задеплой с нуля / развернуть | **A: Создать + задеплоить** |
| обновить / задеплой / загрузить ветку / редеплой | **B: Обновить существующее** |
| статус / как дела / что с приложением / проверь | **C: Проверить статус** |
| запусти / старт / включи | **D: Запустить** |
| останови / стоп / выключи | **E: Остановить** |
| удали / снести / delete / убери | **F: Удалить** |
| принять изменения / смёрджи / merge | **G: Merge ветки** |
| создать проект / загрузить сборку / новый проект из файла | **H: Создать проект из сборки** |

## Шаг 2: Получи токен

```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action get-token
```

Если ошибка — сообщи пользователю что нужно задать env vars:
`ELEMENT_BASE_URL`, `ELEMENT_CLIENT_ID`, `ELEMENT_CLIENT_SECRET`.

---

## Сценарий A: Создать новое приложение и задеплоить

### A1. Проверь project-id
Если `ELEMENT_PROJECT_ID` не задан:
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action list-projects
```
Спроси пользователя: "Выбери проект из списка (укажи id или имя)."
Сохраняй выбранный `project-id` для следующих шагов.

### A2. Определи space-id
Если `ELEMENT_SPACE_ID` не задан:
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action list-spaces
```
- Если пространство **одно** — используй его `id` как `space-id`. Предложи пользователю сохранить в `.env`: `ELEMENT_SPACE_ID=<id>`.
- Если пространств **несколько** — покажи список и спроси пользователя выбрать.
- Если пространств **нет** — сообщи пользователю, создать пространство нужно через веб-консоль.

### A3. Создай приложение
Спроси имя приложения если не указано. Затем:
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action create-app --name <name> --space-id <space-id>
```
Сохрани `id` из ответа как `app-id`.

### A4. Найди или создай ветку
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action list-branches --project-id <project-id> --branch-name <branch>
```
Где `<branch>` — значение `ELEMENT_BRANCH` (по умолчанию: `main`).

- Если ветка **найдена** → возьми её `id` как `branch-id`
- Если ветка **не найдена** → создай:
  ```bash
  python3 .claude/skills/xbsl-deploy/scripts/api.py --action create-branch --project-id <project-id> --branch-name <branch> --app-id <app-id>
  ```
  Используй `id` из ответа как `branch-id`.

Если ветка найдена, но `branch.application.id != app-id` → привяжи:
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action update-branch --branch-id <branch-id> --app-id <app-id>
```

### A5. Запусти приложение
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action start-app --app-id <app-id>
```

### A6. Жди Running
Опрашивай каждые 10 сек, до 5 мин:
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action get-app --app-id <app-id>
```
Жди пока `status` == `Running`. Если `status` == `Error` — сообщи `error` пользователю и остановись.
Если 5 мин прошло, а статус не `Running` — сообщи пользователю текущий статус и предложи проверить логи в консоли Элемента.

### A7. Верни ссылку
Из последнего ответа `get-app` возьми поле `uri` и отправь пользователю.

---

## Сценарий B: Обновить приложение из ветки

### B1. Найди приложение
Используй `ELEMENT_APP_ID` или спроси имя и найди:
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action list-apps --name <name>
```
Сохрани `id` как `app-id`.

### B2. Определи project-id
Используй `ELEMENT_PROJECT_ID`. Если не задан — извлеки из ответа B1: поле `project.id` в объекте приложения.
Если поле `project` отсутствует или пустое:
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action list-projects
```
Спроси пользователя выбрать проект. Сохрани как `project-id`.

### B3. Создай дамп (страховка перед изменениями)
Дамп нужен как точка отката на случай проблем после деплоя.
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action create-dump --app-id <app-id>
```
Сохрани `id` из ответа как `dump-id`. Опрашивай статус каждые 10 сек (до 3 мин):
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action get-dump --app-id <app-id> --dump-id <dump-id>
```
Жди пока `status` станет `Done` или `Completed`.
**Если дамп завершился ошибкой или не готов за 3 мин — остановись и сообщи пользователю. Не продолжай.**

### B4. Найди ветку
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action list-branches --project-id <project-id> --branch-name <branch>
```

### B5. Привяжи ветку к приложению (если нужно)
Если `branch.application.id != app-id`:
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action update-branch --branch-id <branch-id> --app-id <app-id>
```

### B6. Перезапусти (подхвати изменения из репозитория)
Сначала останови (если приложение не `Stopped`):
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action stop-app --app-id <app-id>
```
Жди `Stopped` (опрос каждые 10 сек, до 3 мин). Затем запусти:
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action start-app --app-id <app-id>
```

### B7. Жди Running → верни URL (как A5-A6)

---

## Сценарий C: Статус приложения

```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action get-app --app-id <app-id>
```

Выведи пользователю:
- `status` (Running / Stopped / Error / ...)
- `uri` — ссылка на приложение
- `error` — если есть
- `current-task` — текущая задача если есть
- `technology-version`

---

## Сценарий D: Запустить приложение

```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action start-app --app-id <app-id>
```
Жди `Running` (опрос каждые 10 сек, до 5 мин) → верни статус и ссылку.
Если таймаут — сообщи текущий статус и предложи проверить логи в консоли Элемента.

---

## Сценарий E: Остановить приложение

```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action stop-app --app-id <app-id>
```
Жди `Stopped` (опрос каждые 10 сек, до 3 мин) → сообщи что остановлено.
Если таймаут — сообщи текущий статус.

---

## Сценарий F: Удалить приложение

**Предупреди пользователя** что действие необратимо. Жди подтверждения.

Если приложение не `Stopped`:
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action stop-app --app-id <app-id>
```
Жди `Stopped` (опрос каждые 10 сек, до 3 мин). Затем:
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action delete-app --app-id <app-id>
```

Если ветка создавалась скиллом — предложи удалить и её:
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action delete-branch --branch-id <branch-id>
```

---

## Сценарий G: Принять изменения (merge ветки)

Если `branch-id` не известен — найди ветку. Для этого нужен `project-id` (из `ELEMENT_PROJECT_ID` или спроси пользователя через `list-projects`):
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action list-branches --project-id <project-id> --branch-name <branch>
```

Затем выполни merge:
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action merge-branch --branch-id <branch-id>
```
Сообщи результат.

---

## Сценарий H: Создать проект из файла сборки

Проект на Элементе создаётся загрузкой бинарного файла сборки (`.zip` или артефакт компилятора).
Без файла создать проект через API нельзя.

### H1. Уточни параметры
Спроси пользователя:
- путь к файлу сборки (`--file`)
- имя ветки (`--branch-name`), если нужно зафиксировать (иначе используется `ELEMENT_BRANCH`)
- хэш коммита и сообщение (`--commit-id`, `--commit-message`) — опционально

### H2. Определи space-id
Если `ELEMENT_SPACE_ID` не задан:
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action list-spaces
```
Если пространство одно — используй его автоматически.

### H3. Загрузи сборку и создай проект
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py --action upload-build \
  --file <path> \
  --space-id <space-id> \
  [--branch-name <branch>] \
  [--commit-id <hash>] \
  [--commit-message <msg>]
```
Чтобы добавить сборку к **существующему** проекту, добавь `--project-id <id>`.

Из ответа возьми `project-id` для дальнейших операций (создание приложения, ветки и т.д.).

---

## Правила работы

- **app-id**: берётся из `ELEMENT_APP_ID` → аргумента → поиска по имени
- **project-id**: берётся из `ELEMENT_PROJECT_ID` → аргумента → выбора пользователя
- **branch**: берётся из `ELEMENT_BRANCH` (по умолчанию `main`)
- **Дамп** нужен только перед обновлением существующего приложения (Сценарий B). При создании нового — не нужен.
- **space-id**: берётся из `ELEMENT_SPACE_ID` → автоопределения через `list-spaces` (если пространство одно — используется автоматически, предложи сохранить в `ELEMENT_SPACE_ID`)
- При ошибке API — показывай поле `error` и `details` из ответа
