# Console API v2 — Справочник endpoint-ов

Base URL: `$ELEMENT_BASE_URL` (например `https://1cmycloud.com`)

## Аутентификация

| Метод | Endpoint | Описание |
|---|---|---|
| POST | `/console/sys/token` | Basic Auth (Client-Id:Client-Secret) → Bearer токен |

Токен кешируется в `/tmp/element_token_<hash>.json` (TTL 1ч).

## Приложения

| Метод | Endpoint | Действие |
|---|---|---|
| GET | `/console/api/v2/applications` | Список приложений (фильтр: `?name=...`) |
| GET | `/console/api/v2/applications/{id}` | Получить приложение |
| GET | `/console/api/v2/applications/{id}/status` | Получить только статус (легче, для polling) |
| POST | `/console/api/v2/applications` | Создать приложение |
| DELETE | `/console/api/v2/applications/{id}` | Удалить приложение |
| PUT | `/console/api/v2/applications/{id}/status/start` | Запустить |
| PUT | `/console/api/v2/applications/{id}/status/stop` | Остановить |

### Тело создания приложения (POST)
```json
{
  "source": {
    "type": "repository",
    "image-id": "<project-id>",
    "project-version-id": "<build-image-id>"
  },
  "display-name": "Имя приложения",
  "publication-context": "Имя приложения",
  "development-mode": false,
  "space-id": "<space-id>"
}
```
- `space-id` **обязателен**. Без него сервер вернёт 500.
- `source.image-id` — ID проекта (используется сборка по умолчанию; должна быть установлена).
- `source.project-version-id` — ID конкретной сборки (`image-id` из ответа `upload-build`). Приоритетнее чем `image-id`.
- Только `type: "repository"` поддерживается.

### Поля приложения (ответ)
- `id` — идентификатор
- `name` — имя
- `status` — статус
- `uri` — **ссылка на приложение** (полный путь)
- `project` — связанный проект `{ id, name }` (есть если приложение привязано к ветке)
- `endpoint` — объект веб-адреса (детальная структура — через `/endpoints`)
- `current-task` — текущая фоновая задача
- `technology-version` — версия технологии
- `error` — текущая ошибка, если есть

### Статусы приложения
- `Running` — работает
- `Stopped` — остановлено
- `Starting` — запускается
- `Stopping` — останавливается
- `Initializing` — инициализируется после создания
- `Frozen` — заморожено
- `Error` — ошибка (смотри поле `error`)

## Пространства (Spaces)

| Метод | Endpoint | Описание |
|---|---|---|
| GET | `/console/api/v2/spaces` | Список пространств |
| GET | `/console/api/v2/spaces/{id}` | Информация о пространстве |
| POST | `/console/api/v2/spaces` | Создать пространство |

### Поля пространства
- `id` — идентификатор
- `name` — имя
- `owner` — владелец
- `applications-count` — количество приложений
- `applications-quota` — квота приложений

### Примечание
`space-id` **обязателен** при создании приложения (POST `/console/api/v2/applications`).
Если `ELEMENT_SPACE_ID` не задан — получи список пространств и определи нужное автоматически.

## Проекты

| Метод | Endpoint | Описание |
|---|---|---|
| GET | `/console/api/v2/projects` | Список проектов |
| GET | `/console/api/v2/projects/{id}` | Информация о проекте |
| DELETE | `/console/api/v2/projects/{id}` | Удалить проект (перед удалением нужно удалить все приложения) |
| POST | `/console/api/v2/projects` | Создать новый проект из файла сборки (Content-Type: octet-stream) |
| GET | `/console/api/v2/projects/{id}/assemblies` | Список сборок проекта |
| POST | `/console/api/v2/projects/{id}/assemblies` | Добавить сборку к существующему проекту (Content-Type: octet-stream) |
| GET | `/console/api/v2/projects/{id}/assemblies/{version}` | Подробная информация о сборке |
| DELETE | `/console/api/v2/projects/{id}/assemblies/{version}` | Удалить сборку |

### Загрузка файла сборки (POST)
- Content-Type: `application/octet-stream` (бинарный файл)
- Query params: `SpaceId`, `BranchName`, `CommitId`, `CommitMessage`, `Version`, `Modified`
- Без `{id}` в пути — создаёт новый проект. С `{id}/assemblies` — добавляет сборку к существующему.

### Поля сборки (ответ AssemblyDto)
- `assembly-version` — версия сборки (используется как `{version}` в path)
- `created` — дата создания
- `project-id` — идентификатор проекта
- `project-name` — имя проекта
- `project-version` — версия проекта
- `branch-name` — имя ветки
- `commit-id` — хэш коммита
- `comment` — комментарий
- `modified` — признак модификации относительно VCS

### Обновление приложения на конкретную сборку

```
POST /console/api/v2/applications/{app-id}/project/update
```

```json
{
  "source": {
    "type": "repository",
    "image-id": "<assembly-id>"
  }
}
```

Поля `source`:
- `image-id` — ID конкретной сборки (приоритетнее)
- `project-id` + `assembly-version` — альтернатива: проект + версия сборки

После `project/update` нужен stop → start для применения изменений.

## Ветки

> **Важно**: ветки 1С:Элемент — это механизм **внутренней групповой разработки** платформы (аналог feature-branch для задач, типа `issue/CRM-1`). Это **не GitHub-ветки**. Работают только для проектов с включённым режимом групповой разработки. Если проект типа `Application` без этого режима — API вернёт 503 "does not use export branches". Это штатное поведение, не ошибка конфигурации.

| Метод | Endpoint | Описание |
|---|---|---|
| GET | `/console/api/v2/branches` | Список веток (фильтр: `?project-id=...&name=...`) |
| GET | `/console/api/v2/branches/{id}` | Получить ветку |
| POST | `/console/api/v2/branches` | Создать ветку |
| PUT | `/console/api/v2/branches` | Создать или обновить ветку по имени (upsert) |
| PUT | `/console/api/v2/branches/{id}` | Обновить ветку (application, write-parameters) |
| DELETE | `/console/api/v2/branches/{id}` | Удалить ветку |

### Тело создания ветки (POST)
```json
{
  "name": "main",
  "kind": "development",
  "project": { "id": "<project-id>" },
  "application": { "id": "<app-id>" }
}
```

### Тело merge ветки (PUT /{id})
```json
{
  "name": "<branch-name>",
  "version-stamp": "<current-version-stamp>",
  "write-parameters": { "merge": true }
}
```

### Поля ветки
- `id` — идентификатор
- `name` — имя ветки (внутреннее, напр. `issue/CRM-1`)
- `kind` — `main` / `release` / `development`
- `project` — ссылка на проект
- `repository` — URL git-репозитория (информационное, read-only; не источник кода)
- `application` — привязанное приложение `{ id, name, url }`
- `version-stamp` — для оптимистической блокировки

## Дампы

| Метод | Endpoint | Описание |
|---|---|---|
| GET | `/console/api/v2/applications/{id}/dumps` | Список дампов |
| POST | `/console/api/v2/applications/{id}/dumps` | Создать дамп |
| GET | `/console/api/v2/applications/{id}/dumps/{dump-id}` | Статус дампа |
| DELETE | `/console/api/v2/applications/{id}/dumps/{dump-id}` | Удалить дамп |

### Статусы дампа
- `InProgress` / `Creating` — создаётся (ждать)
- `Done` / `Completed` — готов (можно продолжать)
- `Error` — ошибка (остановить деплой)

## Задачи приложений

| Метод | Endpoint | Описание |
|---|---|---|
| GET | `/console/api/v2/tasks/applications` | Список фоновых задач приложений |
| GET | `/console/api/v2/tasks/{id}` | Информация о задаче |

### Поля задачи
- `id` — идентификатор
- `status` — статус (`InProgress`, `Done`, `Error`)
- `operation-type` — тип операции (например `CreateApplication`, `StartApplication`)
- `start-date` / `end-date` — даты начала и окончания
- `application-id` — идентификатор приложения
- `error-message` — описание ошибки, если есть
