# Авторизация без передачи секретов в чат

Независимо от источника auth state работай только с его путём. Никогда не
открывай, не разбирай, не печатай и не прикладывай содержимое существующего
`storageState`; передавай файл непосредственно Playwright. Допустимы только
проверки существования/доступности пути без чтения JSON.

## Порядок выбора механизма

1. Переиспользуй существующий auth fixture, setup project или `storageState`,
   сохраняя соглашения consumer-проекта.
2. Иначе используй путь из `ELEMENT_AUTH_STATE`, если локальный файл существует.
   Передавай путь непосредственно Playwright.
3. Если готовой сессии нет или она невалидна, предложи интерактивную
   авторизацию в headed Chromium.

До интерактивного входа согласуй semantic-признак app shell: устойчивый heading,
navigation landmark или другой элемент, появляющийся только после успешного
login. В dry-run покажи команду и целевой локальный путь `.auth/<role>.json`;
создание файла и запуск headed browser требуют подтверждения.

Запускай `codegen` через project-local executable и приводи команду для текущей
оболочки. Например, для npm:

```text
POSIX:      npm exec -- playwright codegen "$ELEMENT_APP_URL" --save-storage=".auth/user.json"
PowerShell: npm exec -- playwright codegen "$env:ELEMENT_APP_URL" --save-storage=".auth/user.json"
```

Для другого package manager адаптируй только механизм project-local запуска.
Пользователь самостоятельно вводит логин, пароль, MFA или CAPTCHA в окне
браузера. Никогда не проси прислать эти значения в чат и не автоматизируй их
чтение из clipboard или password manager.

## Проверка сохранённой сессии

После сохранения закрой login context. Создай новый независимый browser context
со `storageState` и перейди по точному `ELEMENT_APP_URL`. State пригоден только
если в этом новом context появился согласованный app-shell признак.

Классифицируй как `BLOCKED/AUTH`, если наблюдается одно из условий:

- redirect на платформенную авторизацию, включая
  `/sys/auth/authorization/` или `auth.1cmycloud.com/.../signin`;
- app-shell признак не появился;
- сессия истекла или не воспроизводится в новом context.

Стандартный `storageState` не сохраняет `sessionStorage`. Если приложение
зависит от него, нужен явно описанный project-specific restore mechanism и его
проверка в новом context. Не делай вид, что обычного state достаточно; без
надёжного restore верни `BLOCKED/AUTH`.

## Несколько ролей и безопасность evidence

Для каждой роли используй отдельный `.auth/*.json` и отдельный browser context.
Не переиспользуй page/context одной роли для доказательства поведения другой.
В отчёте указывай роль и путь к state, но не содержимое файла.

Всегда исключай `.auth/` из Git. Не добавляй state в attachment, HTML report или
trace. Не коммить cookies, local storage либо session storage. Trace может
содержать cookies и сетевые данные: сохраняй его локально и не публикуй
автоматически.
