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
  "source": { "type": "repository" },
  "display-name": "Имя приложения",
  "publication-context": "Имя приложения",
  "development-mode": false
}
```

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
- `Error` — ошибка (смотри поле `error`)

## Проекты

| Метод | Endpoint | Описание |
|---|---|---|
| GET | `/console/api/v2/projects` | Список проектов |
| GET | `/console/api/v2/projects/{id}` | Информация о проекте |

## Ветки

| Метод | Endpoint | Описание |
|---|---|---|
| GET | `/console/api/v2/branches` | Список веток (фильтр: `?project-id=...&name=...`) |
| GET | `/console/api/v2/branches/{id}` | Получить ветку |
| POST | `/console/api/v2/branches` | Создать ветку |
| PUT | `/console/api/v2/branches/{id}` | Обновить ветку (application, write-parameters) |
| DELETE | `/console/api/v2/branches/{id}` | Удалить ветку |

### Тело создания ветки (POST)
```json
{
  "name": "main",
  "kind": "development",
  "project-id": "<project-id>",
  "application": { "id": "<app-id>" }
}
```

### Тело merge ветки (PUT)
```json
{
  "name": "<branch-name>",
  "version-stamp": "<current-version-stamp>",
  "write-parameters": { "merge": true }
}
```

### Поля ветки
- `id` — идентификатор
- `name` — имя (= имя GitHub ветки)
- `kind` — `main` / `release` / `development`
- `project` — ссылка на проект
- `repository` — URL git-репозитория (GitHub, GitLab и др.; read-only)
- `application` — привязанное приложение `{ id, name, url }`
- `version-stamp` — для оптимистической блокировки

## Дампы

| Метод | Endpoint | Описание |
|---|---|---|
| POST | `/console/api/v2/applications/{id}/dumps` | Создать дамп |
| GET | `/console/api/v2/applications/{id}/dumps/{dump-id}` | Статус дампа |

### Статусы дампа
- `InProgress` / `Creating` — создаётся (ждать)
- `Done` / `Completed` — готов (можно продолжать)
- `Error` — ошибка (остановить деплой)
