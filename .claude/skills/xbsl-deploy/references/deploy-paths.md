# Пути деплоя через deploy.py

## Сравнение

| | Путь 1: из исходников | Путь 2: из git-ветки |
|---|---|---|
| Кто собирает | Мы (локально/CI) | Платформа (git pull) |
| Откуда код | Локальная копия репо | GitHub/GitLab напрямую |
| Нужен доступ платформы к git | Нет | Да |
| Предупреждение "не из ветки" | Есть | Нет |
| Env vars | `ELEMENT_PROJECT_ID` | `ELEMENT_BRANCH_ID` |

---

## Путь 1: из исходников (по умолчанию)

Обязательно: `ELEMENT_APP_ID`, `ELEMENT_PROJECT_ID`.

```bash
python3 .claude/skills/xbsl-deploy/scripts/deploy.py \
  [--project-dir PATH] \
  [--app-id APP_ID] \
  [--project-id PROJECT_ID] \
  [--branch BRANCH] \
  [--commit COMMIT_HASH] \
  [--commit-message "msg"] \
  [--version 1.0-42]
```

Шаги: запрос последней версии → сборка `.xasm` → `upload-build` → `project-update` → ожидание `Running`.

**Что исключается из сборки:**
- Папки и файлы, начинающиеся с `.` (`.claude`, `.git`, `.github`, `.env` и любые другие)
- `__pycache__`, `node_modules`
- Файлы `.xasm`, `.gitignore`, `.DS_Store`
- Включаются только: `.yaml`, `.xbsl`, `.md`, `.txt`

**Dry-run** (только сборка, без деплоя):
```bash
python3 .claude/skills/xbsl-deploy/scripts/deploy.py --dry-run
```

---

## Путь 2: из git-ветки

> ⚠️ **Ограничение**: `sync-branch` вызывает внутренний эндпоинт `/console/ui/module/call`, который требует **браузерную сессию** (cookie). Client credentials Bearer токен возвращает **403**. Автоматизировать этот путь через API **невозможно**.
>
> **Единственный способ сделать git pull** — вручную в веб-консоли платформы: раздел «Ветки» → три точки у ветки → «Обновить приложение по ветке».

Платформа сама делает `git fetch + merge` из подключённого репозитория — эквивалент кнопки «Загрузить из ветки» в IDE.

Обязательно: `ELEMENT_APP_ID`, `ELEMENT_BRANCH_ID`.

`ELEMENT_BRANCH_ID` — внутренний ID ветки на платформе. Узнать его можно из HAR-файла браузера при нажатии кнопки «Загрузить из ветки» в IDE (поле `"type": "e1c::console::Team::Branches.Reference"`, значение рядом).

```bash
python3 .claude/skills/xbsl-deploy/scripts/deploy.py \
  --from-branch \
  [--app-id APP_ID] \
  [--branch-id BRANCH_ID]
```

Или через API напрямую:
```bash
python3 .claude/skills/xbsl-deploy/scripts/api.py \
  --action sync-branch \
  --app-id APP_ID \
  --branch-id BRANCH_ID
```

Шаги: `sync-branch` (платформа делает git pull) → ожидание `Running`.
