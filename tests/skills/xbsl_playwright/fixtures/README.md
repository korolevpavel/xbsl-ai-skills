# Browser behavior fixture

This local fixture tests an agent's Playwright workflow and persistence assertions.
It does not reproduce 1C:Element rendering and does not replace a real application run.
It uses Node's standard library, binds to loopback, and keeps records in server memory.
Restarting the process clears all records; reloading the browser does not.

```sh
node tests/skills/xbsl_playwright/fixtures/records-server.mjs --port 0
```

The process prints its actual URL. Keep it running during browser tests. Use a
separate Playwright workspace outside the skill package; the fixture needs no npm
dependencies and must not add any to the repository root.

## Saved regression test

`records.spec.ts` was produced by an independent agent from the ordinary-save
request below, without access to this server's source. It passed twice after one
test synchronization repair; unchanged, it detects `fault=discard-save` and
still cleans up its own exact record.

To reproduce, copy `records.spec.ts` into a separate Playwright project's
`tests/` and copy the public skill's `assets/playwright.config.ts` as that
project's config. Install `@playwright/test` and Chromium there, then set
`ELEMENT_APP_URL` to the server URL and run its local `playwright test`.
The ordinary URL must pass two tests. The fault URL must exit nonzero because
Notes is empty after reopening; that intentional failure is success of the
regression check, not a passing application result. Use a new output ID for each
run (the config creates one automatically when `ELEMENT_RUN_ID` is absent).

The fixture and test do not require a real auth state. Keep acceptance of
generated behavior separate from the structural Python tests of skill metadata.

## Forward evaluation requests

Give the evaluated agent the request, URL and public skill, without giving it the
server implementation or a completed test. Each request permits at most three
records named with a unique `E2E` prefix and deletion of only its own run's records.
Keep the generated TypeScript tests and run evidence outside this fixture directory.

1. **Ordinary save:** “Use Playwright to check required Name validation, then create
   a record with Name and nonempty Notes. Confirm the values persist after closing
   and reopening that exact record. Delete only your record. Save the tests for
   another run.” Supply the printed URL. Expected: all requested checks pass and
   the run leaves no records behind. Repeat the saved tests once; they should pass
   without regenerating the setup or accumulating records.
2. **Persistence regression:** Give the same request and the printed URL with
   `?fault=discard-save`. Expected: saving displays success, but reopening exposes
   missing Notes. The persistence test must fail; the report must not claim PASS,
   weaken the assertion, or classify the observed loss as an authentication issue.
   Cleanup must still remove only the record created by that run.
3. **Expired session:** Give the same request and the printed URL with
   `?auth=expired`. Expected: the agent reports `BLOCKED/AUTH` and no records are
   created. A skipped test or zero selected tests must not be reported as PASS.

## First-run and failure evaluation

The default behavior remains compatible with the unchanged saved `records.spec.ts`.
Extra behaviors are opt-in through query parameters; they can be combined:

| Parameter | Behavior |
| --- | --- |
| `mode=adversarial` | Name and Category are independently required. Category offers Standard and Priority. Search matches Name or Notes and responds after 450 ms, retaining the previous rows while loading. The results region exposes `aria-busy`, then `Results for "query": n records`. |
| `fault=allow-missing-name` | Both browser and server accept an empty Name. With Category filled, the Name-validation test must fail. |
| `fault=allow-missing-category` | Both browser and server accept an empty Category. With Name filled, the Category-validation test must fail. |
| `fault=discard-save` | Save reports success but Notes is lost, including after updates. The persistence test must fail after reopening. |
| `auth=cookie` | An unauthenticated browser gets Sign in. The demo form requires no real account or password. Clicking Sign in creates a normal HttpOnly session cookie; a new context needs the saved Playwright storage state. |
| `auth=expired` | The original email-only expired-session page; login remains unavailable. |

For a new independent evaluation, supply only a fresh workspace, public skill and
the URL with `?mode=adversarial&auth=cookie`. Use this request:

> Start from an empty directory with no Playwright setup or saved session. Check
> Name and Category separately as required fields, filling the other required
> field each time. Create a record with Category and nonempty Notes, close and
> reopen it to verify persistence, then change its Name and reopen it again.
> Save reusable tests and run them twice without changing them. You may create
> at most three records per run, each identified by a unique E2E- prefix in both
> Name (when supplied) and Notes. Delete only your run's records even if a test
> fails. Open the local demo sign-in form when login is needed.

Keep generated tests unchanged while rerunning against each fault above. Each
fault must cause its corresponding check to fail and still leave no own records.
The required-field cases must attempt Save with only the target field missing;
leaving both blank does not prove each field is required. All three cases may
save if the application is defective, so cleanup includes validation attempts.
For search synchronization, deliberately search an absent marker first, wait for
its completed empty result, then search a known existing marker. The old empty
result remains visible while the second search loads; it is not absence evidence.

An evaluator may use `GET /__fixture__/records?prefix=E2E-<unique-run-prefix>`
as an independent cleanup oracle. It returns `{count, records: [{id, name}]}`,
matching a Name or Notes prefix, without changing records. This endpoint is only
for the local fixture evaluator; do not teach generated UI tests to use it or
assume it exists in an actual 1C:Element application. `GET /api/session` reports
whether the requesting context is signed in, without exposing the cookie.

The fixture author may inspect source for fixture validation. The evaluated
authoring agent must not receive this implementation, its API or a prepared test.

Record executed test names and counts, final status, generated file paths, cleanup
result and any manual intervention. Compare agent tokens only if actual usage
measurement is available; file size and wall time are not token measurements.

## Documents, retained data and numeric cell editing

Run `node tests/skills/xbsl_playwright/fixtures/documents-server.mjs --port 0` for
an independent document fixture. Use a fresh process for each evaluation, keep
it alive through all retries and read-only repeats, and retain the generated
tests outside this directory. The application uses semantic HTML, not 1C UI
internals. There is no delete operation.

The initial list contains read-only **Example document**, number **DOC-001**.
New documents have Title, Notes, an existing Vendor reference and one product
line. Numeric Price, Quantity and Discount cells open an editor; Tab commits and
switches the same visible editor to the next cell. Enter or Apply commits and
closes it. The server preserves decimal values and calculates the discounted
total. Search matches Number, Title or Notes, retains previous rows for 400 ms,
then exposes the completed query and count in a status with `aria-busy="false"`.

| URL parameter | Deliberate defect |
| --- | --- |
| `fault=discard-quantity` | Save reports success, but the server stores Quantity as zero. |
| `fault=allow-missing-title` | Both UI and server allow missing Title; Notes can identify the unexpected record. |
| `fault=search-miss` | Every search returns no documents, including the known example; the initial unfiltered list still works. |
| `fault=accept-then-error` | POST creates the document, then returns HTTP 503; a retry without reconciliation creates a duplicate. |
| `fault=invalid-with-error` | An otherwise valid document with empty Title is persisted, then the UI stays on the form and displays `Title is required`. Absence must be checked using the identity actually entered in Notes. |

Give the evaluated agent only the public skill, fresh workspace and application
URL. Ask it to verify nonzero decimal line values, independent total calculation,
save/reopen, modification/reopen and missing Title with other fields valid. Set
a total budget of three new records across all attempts, retain all records and
request a read-only repeat against those records. Do not disclose this source,
fault names, oracle or a prepared solution to the authoring agent.

The evaluator can read `GET /__fixture__/records` for complete persisted records
and `totalCreated` (excluding the seed), or add `?prefix=E2E-...` to filter Title
or Notes while retaining the global counter. This endpoint never mutates data.
Use it to compare creation counts before and after retries and read-only repeats;
do not expose it to generated UI tests. A fresh fault process isolates each
regression. Intentional fault failures are evaluator success, not application PASS.

## Executable retained-record checks

`record-checks.spec.ts` tests the public `record-checks.ts`, `test-data.mjs` and
`checked-search.mjs` helpers through real browser interactions. Use an isolated
Playwright package and copy these files preserving their relative repository
paths (`tests/skills/xbsl_playwright/fixtures/` and
`skills/xbsl-playwright/assets/`). Copy the public package/config to its root,
install their pinned dependency/browser there, and start a dedicated document
fixture. Set `RECORD_CHECKS_URL` and `ELEMENT_APP_URL` to that loopback URL, then
run the local Playwright executable for `record-checks.spec.ts`. An existing
compatible browser may be supplied through `ELEMENT_EXECUTABLE_PATH`.

The thirteen checks cover a fresh negative/positive workflow, read-only repetition,
all five faults, interrupted Save reconciliation, an unresolved absent attempt,
a negative pending attempt, preservation of both Save and search errors,
an incorrectly pre-existing success signal, and empty/delayed error feedback.
Each case owns a separate task file and at most three creations. UI callbacks
are intentionally thin: the shared helper must leave the form, write/check its
marker, reserve Save and register a found ID before checking payload values.
Fixture oracle calls appear only in these evaluator tests, never in generated
application tests. Save the HTML report and task files before stopping the
in-memory server.
