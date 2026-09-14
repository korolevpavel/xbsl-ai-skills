import { expect, type Locator } from '@playwright/test';
import { expectAbsentBySearch } from './checked-search.mjs';

type SavedRecord<T> = {
  marker: string; values: T; status: string; everCreated: boolean;
  observed?: { id: string };
};
type Data<T> = {
  record(key: string, values?: T): SavedRecord<T>;
  beginCreate(key: string): SavedRecord<T>;
  found(key: string, observed: { id: string }): SavedRecord<T>;
  absent(key: string): SavedRecord<T>;
};
type CommonUI<T> = {
  list(): Promise<void>;
  search(query: string): Promise<string[]>;
  newRecord(): Promise<void>;
  fill(values: T): Promise<void>;
  marker: Locator;
  // Wait for an outcome. Expected validation is an outcome, not a transport error.
  save(validationText?: string): Promise<void>;
};
type Options<T> = {
  data: Data<T>; key: string; values: T; mode?: 'prepare' | 'verify';
};

// saved must be a new outcome, e.g. the list appearing after write-and-close.
export async function saveWithFeedback({ button, saved, error, validationText }: {
  button: Locator; saved: Locator; error: Locator; validationText?: string;
}): Promise<void> {
  await expect(saved, 'SAVE: the success signal must be hidden before Save.').toBeHidden();
  await button.click();
  await expect(saved.or(error).filter({ visible: true }).first()).toBeVisible();
  if (await error.isVisible()) {
    await expect(error, 'SAVE: visible error feedback must contain a message.').toHaveText(/\S/);
    const message = (await error.innerText()).trim();
    if (message !== validationText) throw new Error(`SAVE: ${message}`);
  }
}

function raise(errors: unknown[]) {
  if (errors.length === 1) throw errors[0];
  if (errors.length > 1) throw new AggregateError(errors, 'Save/validation failed and reconciliation also failed.');
}

async function search<T>(ui: CommonUI<T>, query: string): Promise<string[]> {
  await ui.list();
  const ids = await ui.search(query);
  if (!Array.isArray(ids) || ids.some(id => typeof id !== 'string' || !id.trim())) {
    throw new Error('SEARCH: return observed record IDs as an array of nonempty strings.');
  }
  return ids;
}

async function fillMarker<T>(ui: CommonUI<T>, record: SavedRecord<T>) {
  await ui.marker.fill(record.marker);
  await expect(ui.marker).toHaveValue(record.marker);
}

export async function checkKeptRecord<T>({ data, key, values, mode = 'verify', ui }: Options<T> & {
  ui: CommonUI<T> & { open(id: string): Promise<void>; assertSaved(values: T): Promise<void> };
}): Promise<SavedRecord<T>> {
  let record = data.record(key, values);
  const errors: unknown[] = [];
  if (!record.everCreated && record.status !== 'pending') {
    if (mode !== 'prepare') throw new Error('PRECONDITION: saved record is missing; verify cannot create it.');
    await ui.list();
    await ui.newRecord();
    await ui.fill(record.values);
    await fillMarker(ui, record);
    data.beginCreate(key);
    try { await ui.save(); } catch (error) { errors.push(error); }
  }
  try {
    const ids = await search(ui, record.marker);
    if (ids.length !== 1) {
      throw new Error(`PRECONDITION: expected one saved record, found ${ids.length}; creation will not be repeated.`);
    }
    if (record.everCreated && record.observed?.id !== ids[0]) {
      throw new Error('PRECONDITION: search found a different record ID.');
    }
    record = data.found(key, { id: ids[0] });
  } catch (error) { errors.push(error); }
  raise(errors); // A found record must never turn a failed Save into PASS.
  await ui.list();
  await ui.open(record.observed!.id);
  await expect(ui.marker).toHaveValue(record.marker);
  await ui.assertSaved(record.values);
  return record;
}

export async function checkRejectedRecord<T>({ data, key, values, mode = 'verify', ui, known, errorText }: Options<T> & {
  ui: CommonUI<T> & { makeInvalid(): Promise<void>; rejection: Locator };
  known: { id: string; marker: string }; errorText: string;
}): Promise<SavedRecord<T>> {
  if (mode !== 'prepare') throw new Error('PRECONDITION: negative Save checks run only in prepare mode.');
  const record = data.record(key, values);
  if (record.everCreated) throw new Error('APPLICATION: this invalid record was already saved.');
  if (!errorText.trim()) throw new Error('Specify the observed validation message for this field.');

  async function reconcileAbsence() {
    await expectAbsentBySearch({
      known, candidate: record, queryFor: (item: { marker: string }) => item.marker,
      search: async (query: string) => {
        const ids = await search(ui, query);
        if (query === record.marker && ids.length === 1) data.found(key, { id: ids[0] });
        return ids;
      },
    });
    data.absent(key);
  }

  if (record.status === 'pending') await reconcileAbsence();
  await ui.list();
  await ui.newRecord();
  await ui.fill(record.values);
  await ui.makeInvalid();
  await fillMarker(ui, record);
  data.beginCreate(key);
  const errors: unknown[] = [];
  try {
    await ui.save(errorText);
    await expect(ui.rejection).toHaveText(errorText);
  } catch (error) { errors.push(error); }
  try { await reconcileAbsence(); } catch (error) { errors.push(error); }
  raise(errors);
  return data.record(key);
}
