# Запуск, evidence и диагностика

## Preflight и targeted run

Перед запуском проверь, не раскрывая секреты:

- доступность Node.js, выбранного package manager, локального
  `@playwright/test` и Chromium;
- наличие `ELEMENT_APP_URL` и нужных auth-state paths;
- доступность URL и соответствие ожидаемой revision, если она обязательна;
- наличие однозначных опорных данных, ролей и разрешения на stateful changes.

Отсутствующий runtime, браузер, DNS, недоступный URL или 5xx дают
`BLOCKED/ENVIRONMENT`. Несовпадение обязательной revision либо нехватка данных,
прав или второй identity дают `BLOCKED/PRECONDITION`. Неполученное подтверждение
изменений данных даёт `BLOCKED/SAFETY`.

Запускай один нужный spec/test title через project-local executable и выбранный
package manager. Не запускай весь suite, пока targeted scope не прошёл или
пользователь отдельно не попросил регрессию. Записывай фактическую команду и
exit code.

## Классификация падения

Изучи Playwright error, screenshot и trace. Не публикуй trace и не выводи
storage state.

1. Сначала исключи redirect/login (`AUTH`), runtime/URL (`ENVIRONMENT`),
   отсутствующие данные/роль (`PRECONDITION`) и отсутствие разрешения (`SAFETY`).
2. `TEST` подтверждён, когда evidence показывает ошибку TypeScript/setup,
   неверный или неоднозначный locator, ошибочную синхронизацию либо assertion,
   не выражающий согласованный критерий. Исправь минимально и повтори тот же
   targeted test.
3. `APPLICATION` подтверждён, когда locator и предусловия надёжны, действие
   выполнено, а наблюдаемое состояние нарушает неизменённый критерий. Верни
   `FAIL/APPLICATION`; не меняй application code и не ослабляй assertion.
4. Если различить дефект теста и приложения надёжно не удалось, не объявляй
   `FAIL/APPLICATION`: верни `UNVERIFIED/TEST` и опиши недостающее доказательство.

Новый симптом после repair анализируй заново. Не продолжай бесконечные retries:
остановись после первого подтверждённого внешнего blocker/дефекта приложения
или когда дальнейший repair требует нового scope.

## Evidence

Для каждого падения проверь фактически созданные пути, не выдумывая их:

- trace archive из `test-results/` при `retain-on-failure`;
- screenshot из `test-results/` при `only-on-failure`;
- `playwright-report/index.html` от HTML reporter.

Успешный targeted rerun не должен стирать описание исходного падения и
выполненного repair. Если reporter очистил старый output, сохрани в отчёте пути
и факт существования evidence до rerun, не копируя чувствительные файлы в Git.

Cleanup запускай и классифицируй отдельно от основного сценария. Ошибка cleanup
не превращает прошедшие assertions в `FAIL/APPLICATION`, но должна оставить
общий результат не `PASS`, если согласованный обязательный cleanup не завершён;
укажи точные идентификаторы оставшихся данных.

## Формат итогового отчёта

Для каждого сценария укажи:

- имя, обязательность, `status`, `reason` и краткое наблюдаемое доказательство;
- пройденные и упавшие assertions;
- role/auth mechanism без секретов;
- команду, exit code, trace, screenshot и HTML report paths;
- repair и targeted rerun;
- data created, cleanup status и ограничения.

Затем вычисли общий `status/reason`. Общий `PASS/NONE` допустим только при
`PASS/NONE` всех обязательных сценариев. Не формулируй его как отсутствие всех
дефектов приложения.
