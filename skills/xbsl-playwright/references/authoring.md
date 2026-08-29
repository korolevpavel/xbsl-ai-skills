# Создание и изменение Playwright-тестов

## Выбор существующего setup

Сначала найди ближайшую точку владения Node-проектом: `package.json`, поле
`packageManager`, workspace-конфигурацию, lockfile и `playwright.config.*`.

- Если Playwright настроен, сохрани package manager, закреплённую версию
  `@playwright/test`, конфигурацию, testDir, fixtures, auth setup, reporters,
  Page Objects и naming conventions. Не заменяй config и не создавай второй
  scaffold.
- Если Playwright не настроен, но package manager определяется однозначно,
  используй его только внутри нового независимого `e2e/` с собственными
  `package.json` и lockfile.
- Если manager определить нельзя, используй npm внутри нового `e2e/`.
- Lockfiles разных managers в одной точке владения либо иная реальная
  неоднозначность — `BLOCKED/PRECONDITION` до выбора пользователя. Не меняй
  manager существующего проекта.

Новый `e2e/` не регистрируй в существующем workspace и не меняй корневые
`package.json`, workspace-конфигурацию или lockfile consumer-проекта. Если
выбранный manager по умолчанию поднимается к workspace root, используй его
штатный режим изолированного пакета. Если собственный lockfile без изменения
root гарантировать нельзя, остановись с `BLOCKED/PRECONDITION` и запроси решение.

Не запускай команду package manager, которая может неявно скачать пакет, пока
установка не подтверждена. Используй project-local Playwright executable.

## Новый изолированный пакет

Создавай только после подтверждения:

```text
e2e/
├── package.json
├── <lockfile>
├── playwright.config.ts
├── .gitignore
└── tests/
    └── <scenario>.spec.ts
```

`package.json` должен быть private и содержать `@playwright/test` в
`devDependencies`. Фиксируй реально разрешённую package manager версию и
полученный собственный lockfile. Зависимости нового setup устанавливай только в
`e2e/`; не добавляй их в consumer root или репозиторий скиллов.

Дефолты `playwright.config.ts`:

- TypeScript и `@playwright/test`;
- `testDir: "./tests"`, Chromium и один worker;
- `baseURL` равен полному `ELEMENT_APP_URL`;
- reporters `list` и `html` (`open: "never"`);
- `trace: "retain-on-failure"`, `screenshot: "only-on-failure"`,
  `video: "off"`;
- CI-конфигурация отсутствует, если пользователь отдельно её не запросил.

Заверши работу с понятной ошибкой, если `ELEMENT_APP_URL` отсутствует. Первый
переход должен использовать точное значение переменной, например
`page.goto(process.env.ELEMENT_APP_URL!)`. Не используй `page.goto("/")`:
значимый prefix вида `/applications/<name>` иначе может потеряться.

Добавь в `e2e/.gitignore`:

```gitignore
.auth/
node_modules/
test-results/
playwright-report/
blob-report/
```

Если setup существующий, проверь эквивалентные ignore rules в его реальном
layout и предложи минимальное дополнение вместо дублирования файлов.

## Locators и assertions

Проверяй каждый locator против доступного UI. Приоритет:

1. `getByRole`;
2. `getByLabel`;
3. `getByPlaceholder`;
4. scoped `getByText`;
5. устойчивый `data-testid`, уже предусмотренный приложением.

Не используй без отдельного доказанного обоснования XPath, внутренние CSS-
классы платформы, длинные CSS-цепочки, координатные клики и локаторы по
случайному порядку элементов. Не применяй `waitForTimeout`, произвольный sleep
или retry, скрывающий нестабильность.

Используй web-first assertions (`expect(locator).toBeVisible()`, `toHaveText`,
`toHaveValue` и аналогичные) и ожидай наблюдаемое состояние. Проверяй бизнес-
результат: например, после сохранения повторно открой точную запись и сравни
сохранённые значения, а не только факт нажатия кнопки.

Page Object вводи только при реальном повторном использовании. Не переносись в
него app URL, секреты или assertion, важный только одному сценарию.

## Stateful data и RLS

- Для создаваемых данных формируй уникальный run ID. Если поле для него
  недоступно, после записи захвати точный неизменяемый идентификатор, например
  присвоенный номер.
- Отсутствующую или неоднозначную опорную запись классифицируй как
  `BLOCKED/PRECONDITION`; не выбирай случайный первый элемент.
- Рассчитывай ожидаемые бизнес-значения внутри теста и проверяй их после
  сохранения/повторного чтения.
- Cleanup удаляет только точные записи текущего run ID/идентификатора, в
  обратном порядке зависимостей. Широкие условия удаления запрещены.
- Для RLS используй отдельные auth state и независимые browser contexts.
  Контрольный context владельца должен подтвердить существование записи, прежде
  чем отсутствие в другом context считать доказательством ограничения доступа.
