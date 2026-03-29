# CI/CD: деплой на 1С:Элемент

## GitHub Actions (проверено, работает)

При пуше в `master` автоматически собирает `.xasm` из исходников и деплоит на платформу.

**Шаг 1.** Создай `.github/workflows/deploy.yml` в корне репозитория:

```yaml
name: Deploy to 1C:Element

on:
  push:
    branches:
      - master
    paths:
      - '**/*.yaml'
      - '**/*.xbsl'
      - '!.github/**'
      - '!**/.claude/**'

jobs:
  deploy:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Deploy to 1C:Element
        env:
          ELEMENT_BASE_URL: ${{ secrets.ELEMENT_BASE_URL }}
          ELEMENT_CLIENT_ID: ${{ secrets.ELEMENT_CLIENT_ID }}
          ELEMENT_CLIENT_SECRET: ${{ secrets.ELEMENT_CLIENT_SECRET }}
          ELEMENT_APP_ID: ${{ secrets.ELEMENT_APP_ID }}
          ELEMENT_PROJECT_ID: ${{ secrets.ELEMENT_PROJECT_ID }}
        run: |
          python3 <путь-к-проекту>/.claude/skills/xbsl-deploy/scripts/deploy.py \
            --project-dir <путь-к-проекту> \
            --branch "$GITHUB_REF_NAME" \
            --commit "$GITHUB_SHA" \
            --commit-message "${{ github.event.head_commit.message }}"
```

Замени `<путь-к-проекту>` на путь от корня репозитория до папки проекта (например `vendor/myproject`).

**Шаг 2.** Добавь секреты: `Settings → Secrets and variables → Actions → New repository secret`:

| Secret | Откуда взять |
|--------|-------------|
| `ELEMENT_BASE_URL` | Базовый URL платформы, например `https://1cmycloud.com` |
| `ELEMENT_CLIENT_ID` | Client-Id из настроек приложения на платформе |
| `ELEMENT_CLIENT_SECRET` | Client-Secret из настроек приложения на платформе |
| `ELEMENT_APP_ID` | ID приложения — из `list-apps` или `.env` |
| `ELEMENT_PROJECT_ID` | ID проекта — из `list-projects` или `.env` |

## GitLab CI

Аналогично, используй переменные окружения GitLab CI:

```yaml
deploy:
  script:
    - python3 <путь-к-проекту>/.claude/skills/xbsl-deploy/scripts/deploy.py
        --project-dir <путь-к-проекту>
        --branch "$CI_COMMIT_BRANCH"
        --commit "$CI_COMMIT_SHA"
        --commit-message "$CI_COMMIT_MESSAGE"
  only:
    - master
```

Секреты задаются в `Settings → CI/CD → Variables`.

## Env vars для любой CI системы

```
ELEMENT_BASE_URL=https://1cmycloud.com
ELEMENT_CLIENT_ID=...
ELEMENT_CLIENT_SECRET=...
ELEMENT_APP_ID=...
ELEMENT_PROJECT_ID=...
```
