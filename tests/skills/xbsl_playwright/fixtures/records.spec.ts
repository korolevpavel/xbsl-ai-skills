import { writeFile } from 'node:fs/promises';
import { test, expect, type Page } from '@playwright/test';

const appURL = process.env.ELEMENT_APP_URL!;
const runID = process.env.ELEMENT_RUN_ID!;

function exactRow(page: Page, name: string) {
  return page.getByRole('row').filter({
    has: page.getByRole('cell', { name, exact: true }),
  });
}

async function listRecords(page: Page) {
  await page.goto(appURL);
  await expect(page.getByRole('heading', { name: 'Records', exact: true })).toBeVisible();
}

test('Name is required and an invalid record is not saved', async ({ page }) => {
  await listRecords(page);
  // This observed list has no pagination; compare the complete displayed rows.
  const before = await page.getByRole('table').getByRole('row').allTextContents();
  await page.getByRole('button', { name: 'New record', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Name', exact: true })).toHaveValue('');
  await page.getByRole('textbox', { name: 'Notes', exact: true }).fill(`E2E-required-${runID}`);
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('Name is required');
  await expect(page.getByRole('heading', { name: 'New record', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await listRecords(page);
  await expect(page.getByRole('table').getByRole('row')).toHaveText(before);
});

test('Name and Notes persist after closing and reopening; own record is deleted', async ({ page }, testInfo) => {
  const name = `E2E-persist-${runID}`;
  const notes = `Notes saved for ${name}\nSecond line: 123, текст.`;
  const evidence = { name, notes, saveRequested: false, reopened: false, cleanup: 'not needed' };
  const recordFile = testInfo.outputPath('own-record.json');
  const recordEvidence = () => writeFile(recordFile, JSON.stringify(evidence, null, 2) + '\n');

  await listRecords(page);
  await expect(exactRow(page, name)).toHaveCount(0);
  let scenarioError: unknown;
  try {
    await page.getByRole('button', { name: 'New record', exact: true }).click();
    await page.getByRole('textbox', { name: 'Name', exact: true }).fill(name);
    await page.getByRole('textbox', { name: 'Notes', exact: true }).fill(notes);
    evidence.saveRequested = true;
    evidence.cleanup = 'pending';
    await recordEvidence();
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    // Save can return to the list or leave the saved form open. Both observed
    // surfaces must lead to the exact record, then a fresh reopen below.
    await expect.poll(async () =>
      await exactRow(page, name).count()
      || Number(await page.getByRole('button', { name: 'Delete', exact: true }).isVisible())
    ).toBe(1);
    if (await page.getByRole('button', { name: 'Close', exact: true }).isVisible()) {
      await page.getByRole('button', { name: 'Close', exact: true }).click();
    }
    await listRecords(page);
    await expect(exactRow(page, name)).toHaveCount(1);
    await exactRow(page, name).getByRole('button', { name: 'Open', exact: true }).click();
    await expect(page.getByRole('textbox', { name: 'Name', exact: true })).toHaveValue(name);
    await expect(page.getByRole('textbox', { name: 'Notes', exact: true })).toHaveValue(notes);
    evidence.reopened = true;
    await recordEvidence();
  } catch (error) {
    scenarioError = error;
  } finally {
    if (evidence.saveRequested) {
      try {
        // Reconcile the exact marker even if Save's response was interrupted.
        // Never create another record in this cleanup path.
        await listRecords(page);
        await expect(exactRow(page, name)).toHaveCount(1);
        await exactRow(page, name).getByRole('button', { name: 'Open', exact: true }).click();
        await expect(page.getByRole('textbox', { name: 'Name', exact: true })).toHaveValue(name);
        page.once('dialog', dialog => dialog.accept());
        await page.getByRole('button', { name: 'Delete', exact: true }).click();
        await expect(page.getByRole('heading', { name: 'Records', exact: true })).toBeVisible();
        await listRecords(page);
        await expect(exactRow(page, name)).toHaveCount(0);
        evidence.cleanup = 'verified absent from the reloaded Records list';
      } catch (cleanupError) {
        evidence.cleanup = `unverified: ${String(cleanupError)}`;
        scenarioError = scenarioError
          ? new AggregateError([scenarioError, cleanupError], 'Scenario and cleanup failed')
          : cleanupError;
      }
      await recordEvidence();
    }
  }
  if (scenarioError) throw scenarioError;
});
