// Run in an isolated Playwright package with copies preserving this repository layout.
// Start a dedicated documents-server.mjs; RECORD_CHECKS_URL must point to that fixture.
import { expect, test, type Page, type TestInfo } from '@playwright/test';
import assert from 'node:assert/strict';
import { openTestData } from '../../../../skills/xbsl-playwright/assets/test-data.mjs';
import { checkKeptRecord, checkRejectedRecord, saveWithFeedback } from '../../../../skills/xbsl-playwright/assets/record-checks';

const baseURL = process.env.RECORD_CHECKS_URL!;
if (!baseURL || new URL(baseURL).hostname !== '127.0.0.1') throw new Error('Use a dedicated loopback RECORD_CHECKS_URL.');
const values = { title: 'Helper test', vendor: 'North Supplies', product: 'Office supplies', price: 1000, quantity: 2, discount: 10 };
const known = { id: '1', marker: 'Read-only example' };

function adapter(page: Page, url: string) {
  const counts = { save: 0, open: 0, assertions: 0 };
  const heading = page.getByRole('heading', { name: 'Documents', exact: true });
  const rejection = page.getByRole('alert');
  const results = page.getByRole('region', { name: 'Search results', exact: true });
  return {
    counts, marker: page.getByRole('textbox', { name: 'Notes', exact: true }), rejection,
    async list() {
      await page.goto(url);
      await expect(heading).toBeVisible();
      await expect(results.getByRole('status')).toContainText('All documents:');
    },
    async search(query: string) {
      await expect(heading).toBeVisible(); // Fails if the helper forgot to leave the form.
      const input = page.getByRole('searchbox', { name: 'Search documents', exact: true });
      if (await input.inputValue() === query) await input.fill('');
      await input.fill(query);
      await expect(results.getByRole('status')).toContainText(`Results for "${query}":`);
      await expect(results).toHaveAttribute('aria-busy', 'false');
      return results.locator('tbody tr').evaluateAll(rows => rows.map(row => row.getAttribute('data-document-id')!));
    },
    async newRecord() {
      await expect(heading).toBeVisible();
      await page.getByRole('button', { name: 'New document', exact: true }).click();
      await expect(page.getByRole('heading', { name: 'New document', exact: true })).toBeVisible();
    },
    async fill(input: typeof values) {
      await page.getByRole('textbox', { name: 'Title', exact: true }).fill(input.title);
      await page.getByRole('combobox', { name: 'Vendor', exact: true }).selectOption(input.vendor);
      await page.getByRole('combobox', { name: 'Product', exact: true }).selectOption(input.product);
      for (const [column, label] of [['price', 'Price'], ['quantity', 'Quantity'], ['discount', 'Discount']] as const) {
        await page.getByTestId(`line-${column}`).click();
        const editor = page.getByRole('region', { name: 'Active cell editor', exact: true });
        await editor.getByRole('textbox', { name: label, exact: true }).fill(String(input[column]));
        await editor.getByRole('button', { name: 'Apply cell value', exact: true }).click();
        await expect(editor).toBeHidden();
      }
    },
    async save(validationText?: string) {
      counts.save++;
      await saveWithFeedback({ button: page.getByRole('button', { name: 'Save', exact: true }),
        saved: heading, error: rejection, validationText });
    },
    async open(id: string) {
      counts.open++;
      await expect(heading).toBeVisible();
      await page.locator(`tr[data-document-id="${id}"]`).getByRole('button', { name: 'Open', exact: true }).click();
      await expect(page.getByRole('heading', { name: 'Edit document', exact: true })).toBeVisible();
    },
    async assertSaved(input: typeof values) {
      counts.assertions++;
      await expect(page.getByRole('textbox', { name: 'Title', exact: true })).toHaveValue(input.title);
      await expect(page.getByRole('combobox', { name: 'Vendor', exact: true })).toHaveValue(input.vendor);
      await expect(page.getByRole('combobox', { name: 'Product', exact: true })).toHaveValue(input.product);
      for (const [column, label] of [['price', 'Price'], ['quantity', 'Quantity'], ['discount', 'Discount']] as const) {
        await expect(page.getByTestId(`line-${column}`)).toHaveText(`${label}: ${input[column].toFixed(2)}`);
      }
      await expect(page.getByTestId('line-total')).toHaveText((input.price * input.quantity * (1 - input.discount / 100)).toFixed(2));
    },
    async makeInvalid() { await page.getByRole('textbox', { name: 'Title', exact: true }).fill(''); },
  };
}

function setup(page: Page, info: TestInfo, fault = '') {
  const url = new URL(baseURL);
  if (fault) url.searchParams.set('fault', fault);
  const binding = { appURL: url.href, maxCreated: 3, retention: 'keep' };
  const path = info.outputPath('task.json');
  const data = openTestData(path, { ...binding, mode: 'prepare' });
  const ui = adapter(page, url.href);
  return { data, ui, binding, path,
    kept: (mode: 'prepare' | 'verify' = 'prepare') => checkKeptRecord({ data, ui, key: 'document', values, mode }),
    rejected: (mode: 'prepare' | 'verify' = 'prepare') => checkRejectedRecord({ data, ui, key: 'missing-title', values, mode, known, errorText: 'Title is required' }),
  };
}

async function actualOwn(page: Page, data: ReturnType<typeof openTestData>) {
  const result = [];
  for (const record of data.snapshot().records) {
    const url = new URL('/__fixture__/records', baseURL); url.searchParams.set('prefix', record.marker);
    const response = await page.request.get(url.href);
    expect(response.ok()).toBeTruthy();
    result.push(...(await response.json()).records);
  }
  expect(result.length).toBeLessThanOrEqual(3);
  return result;
}

test('healthy: negative leaves the form, proves absence, then kept record verifies without another Save', async ({ page }, info) => {
  const fixture = setup(page, info);
  await fixture.rejected();
  expect(fixture.data.record('missing-title').status).toBe('absent');
  const saved = await fixture.kept();
  const verify = openTestData(fixture.path, fixture.binding);
  await checkKeptRecord({ data: verify, ui: fixture.ui, key: 'document', values });
  expect(fixture.ui.counts.save).toBe(2); // One rejected Save, one actual creation.
  expect(fixture.ui.counts.assertions).toBe(2);
  expect(verify.record('document').observed.id).toBe(saved.observed!.id);
  expect(verify.snapshot().budget).toEqual({ created: 1, pending: 0, remaining: 2 });
  expect(await actualOwn(page, verify)).toHaveLength(1);
});

for (const fault of ['allow-missing-title', 'invalid-with-error']) {
  test(`${fault}: invalid record is accounted before the helper reports failure`, async ({ page }, info) => {
    const fixture = setup(page, info, fault);
    await assert.rejects(fixture.rejected());
    expect(fixture.data.record('missing-title').status).toBe('created');
    expect(fixture.data.snapshot().budget.created).toBe(1);
    expect(await actualOwn(page, fixture.data)).toHaveLength(1);
    await assert.rejects(fixture.rejected(), /already saved/);
    expect(fixture.ui.counts.save).toBe(1);
  });
}

test('discard-quantity: found is durable before payload assertion fails', async ({ page }, info) => {
  const fixture = setup(page, info, 'discard-quantity');
  await assert.rejects(fixture.kept(), /Quantity/);
  expect(fixture.data.record('document').status).toBe('created');
  expect(fixture.data.record('document').observed.id).toBeTruthy();
  await assert.rejects(fixture.kept('verify'), /Quantity/);
  expect(fixture.ui.counts.save).toBe(1);
  expect(await actualOwn(page, fixture.data)).toHaveLength(1);
});

test('accept-then-error: original Save error survives, but verify reuses the captured ID', async ({ page }, info) => {
  const fixture = setup(page, info, 'accept-then-error');
  await assert.rejects(fixture.kept(), /SAVE: Save result unavailable/);
  expect(fixture.data.record('document').status).toBe('created');
  expect(fixture.ui.counts.assertions).toBe(0);
  await fixture.kept('verify');
  expect(fixture.ui.counts.save).toBe(1);
  expect(await actualOwn(page, fixture.data)).toHaveLength(1);
});

test('search-miss: failed positive control cannot release pending or enable the next creation', async ({ page }, info) => {
  const fixture = setup(page, info, 'search-miss');
  await assert.rejects(fixture.rejected(), /positive control failed/);
  expect(fixture.data.record('missing-title').status).toBe('pending');
  await assert.rejects(fixture.kept(), /pending save/);
  expect(fixture.ui.counts.save).toBe(1);
  expect(await actualOwn(page, fixture.data)).toHaveLength(0);
});

test('pending after interrupted Save reconciles in verify without another Save', async ({ page }, info) => {
  const fixture = setup(page, info);
  const record = fixture.data.record('document', values);
  await fixture.ui.list(); await fixture.ui.newRecord(); await fixture.ui.fill(values);
  await fixture.ui.marker.fill(record.marker); fixture.data.beginCreate('document');
  await fixture.ui.save(); // Simulate interruption before found().
  const verify = openTestData(fixture.path, fixture.binding);
  await checkKeptRecord({ data: verify, ui: fixture.ui, key: 'document', values });
  expect(verify.record('document').status).toBe('created');
  expect(fixture.ui.counts.save).toBe(1);
  expect(await actualOwn(page, verify)).toHaveLength(1);
});

test('pending with no match remains unresolved; verify never creates missing data', async ({ page }, info) => {
  const fixture = setup(page, info);
  await assert.rejects(fixture.kept('verify'), /verify cannot create/);
  await assert.rejects(fixture.rejected('verify'), /only in prepare/);
  fixture.data.beginCreate('document');
  await assert.rejects(fixture.kept(), /found 0/);
  expect(fixture.data.record('document').status).toBe('pending');
  expect(fixture.ui.counts.save).toBe(0);
  expect(await actualOwn(page, fixture.data)).toHaveLength(0);
});

test('old negative pending can retry only after checked absence', async ({ page }, info) => {
  const fixture = setup(page, info);
  fixture.data.record('missing-title', values); fixture.data.beginCreate('missing-title');
  await fixture.rejected();
  expect(fixture.data.record('missing-title').status).toBe('absent');
  expect(fixture.ui.counts.save).toBe(1);
  expect(await actualOwn(page, fixture.data)).toHaveLength(0);
});

test('both the original Save failure and reconciliation failure are retained', async ({ page }, info) => {
  const fixture = setup(page, info, 'accept-then-error');
  const searchError = new Error('Search unavailable');
  fixture.ui.search = async () => { throw searchError; };
  const failure = await fixture.kept().then(() => undefined, error => error);
  expect(failure).toBeInstanceOf(AggregateError);
  expect(failure.errors).toHaveLength(2);
  expect(failure.errors[0].message).toContain('SAVE: Save result unavailable');
  expect(failure.errors[1]).toBe(searchError);
  expect(fixture.data.record('document').status).toBe('pending');
  expect(await actualOwn(page, fixture.data)).toHaveLength(1);
});

test('an already visible success signal fails before the real Save', async ({ page }, info) => {
  const fixture = setup(page, info);
  const record = fixture.data.record('document', values);
  await fixture.ui.list(); await fixture.ui.newRecord(); await fixture.ui.fill(values);
  await fixture.ui.marker.fill(record.marker);
  let writes = 0;
  page.on('request', request => { if (request.method() === 'POST') writes++; });
  await assert.rejects(saveWithFeedback({
    button: page.getByRole('button', { name: 'Save', exact: true }),
    saved: page.getByRole('heading', { name: 'New document', exact: true }),
    error: fixture.ui.rejection,
  }), /success signal must be hidden before Save/);
  expect(writes).toBe(0);
  expect(await actualOwn(page, fixture.data)).toHaveLength(0);
});

for (const delayedMessage of [false, true]) {
  test(`visible empty error cannot pass${delayedMessage ? '; delayed transport text is preserved' : ''}`, async ({ page }) => {
    await page.setContent(`<button type="button" onclick="document.querySelector('[role=alert]').hidden=false">Save</button>
      <h1 hidden>Saved</h1><p role="alert" style="min-height:20px" hidden></p>`);
    if (delayedMessage) await page.getByRole('button').evaluate(button => button.addEventListener('click', () => {
      setTimeout(() => { document.querySelector('[role=alert]')!.textContent = 'Server unavailable'; }, 300);
    }));
    await assert.rejects(saveWithFeedback({ button: page.getByRole('button'),
      saved: page.getByRole('heading', { name: 'Saved' }), error: page.getByRole('alert'),
    }), delayedMessage ? /SAVE: Server unavailable/ : /visible error feedback must contain a message/);
  });
}
