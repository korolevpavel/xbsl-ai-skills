import { randomUUID } from 'node:crypto';
import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync,
  renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { isDeepStrictEqual } from 'node:util';

const states = new Set(['planned', 'pending', 'created', 'absent', 'deleted']);
const fail = message => { throw new Error(`Test data: ${message}`); };
const copy = value => JSON.parse(JSON.stringify(value, (_key, item) => {
  if (['undefined', 'function', 'symbol', 'bigint'].includes(typeof item)
    || (typeof item === 'number' && !Number.isFinite(item))) fail('values must preserve exact JSON data.');
  return item;
}));

// One task file, reused across runs. Methods record facts; none acts on the UI.
export function openTestData(file, { appURL, maxCreated, retention, mode = 'verify' }) {
  const path = resolve(file);
  let url;
  try { if (typeof appURL !== 'string') throw new Error(); url = new URL(appURL); }
  catch { fail('appURL must be a full HTTP(S) URL.'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
    fail('appURL must use HTTP(S), without embedded credentials.');
  }
  if (!Number.isSafeInteger(maxCreated) || maxCreated < 0) fail('maxCreated must be a nonnegative integer.');
  if (!['keep', 'cleanup'].includes(retention)) fail('retention must be keep or cleanup.');
  if (!['prepare', 'verify'].includes(mode)) fail('mode must be prepare or verify.');
  const binding = { appURL, maxCreated, retention };

  function validate(data) {
    if (data?.version !== 1 || typeof data.taskID !== 'string' || !data.taskID || !Array.isArray(data.records)) {
      fail('invalid task file; refusing to reset it.');
    }
    for (const [key, value] of Object.entries(binding)) {
      if (data[key] !== value) fail(`${key} differs from the saved task; refusing to reset it.`);
    }
    const keys = new Set();
    const markers = new Set();
    for (const record of data.records) {
      if (!record || typeof record.key !== 'string' || !record.key || keys.has(record.key)
        || typeof record.marker !== 'string' || !record.marker || markers.has(record.marker)
        || !record.values || typeof record.values !== 'object' || Array.isArray(record.values)
        || !states.has(record.status) || typeof record.everCreated !== 'boolean'
        || (record.everCreated && (typeof record.observed?.id !== 'string' || !record.observed.id))
        || (!record.everCreated && record.observed !== undefined)
        || (['planned', 'pending'].includes(record.status) && record.everCreated)
        || (['created', 'deleted'].includes(record.status) && !record.everCreated)) {
        fail('invalid record in task file; refusing to reset it.');
      }
      keys.add(record.key); markers.add(record.marker);
    }
    const { created, pending } = budget(data);
    if (pending > 1 || created + pending > maxCreated) fail('invalid saved creation budget.');
    return data;
  }

  function budget(data) {
    const created = data.records.filter(record => record.everCreated).length;
    const pending = data.records.filter(record => record.status === 'pending').length;
    return { created, pending, remaining: maxCreated - created - pending };
  }

  function read() {
    if (!existsSync(path)) fail('task file is missing; verify never creates a replacement.');
    return validate(JSON.parse(readFileSync(path, 'utf8')));
  }

  function transact(change, initialize = false) {
    if (initialize) mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
    const lock = `${path}.lock`;
    let descriptor;
    try { descriptor = openSync(lock, 'wx', 0o600); }
    catch (error) {
      if (error.code === 'EEXIST') fail(`locked (${lock}); check the other process or stale lock manually.`);
      throw error;
    }
    const temporary = `${path}.${randomUUID()}.tmp`;
    try {
      const data = existsSync(path) ? read() : initialize
        ? { version: 1, taskID: randomUUID(), ...binding, records: [] }
        : fail('task file disappeared; refusing to recreate it.');
      const result = change(data);
      validate(data);
      const output = openSync(temporary, 'wx', 0o600);
      try { writeFileSync(output, JSON.stringify(data, null, 2) + '\n'); fsyncSync(output); }
      finally { closeSync(output); }
      renameSync(temporary, path);
      return copy(result);
    } finally {
      if (existsSync(temporary)) unlinkSync(temporary);
      closeSync(descriptor);
      unlinkSync(lock);
    }
  }

  function entry(data, key) {
    const record = data.records.find(record => record.key === key);
    if (!record) fail(`unknown logical key ${key}; verify never plans replacement data.`);
    return record;
  }

  function prepare() {
    if (mode !== 'prepare') fail('creation is forbidden in verify mode.');
  }

  if (!existsSync(path)) {
    prepare();
    transact(data => data, true);
  } else read();

  return {
    record(key, values) {
      if (typeof key !== 'string' || !key.trim()) fail('logical key must be a nonempty string.');
      return transact(data => {
        const saved = data.records.find(record => record.key === key);
        if (saved) {
          if (values !== undefined && !isDeepStrictEqual(saved.values, copy(values))) {
            fail(`expected values differ for ${key}; reuse the saved values.`);
          }
          return saved;
        }
        prepare();
        if (!values || typeof values !== 'object' || Array.isArray(values)) fail('values must be a JSON object.');
        const record = { key, marker: `E2E-${randomUUID()}`, values: copy(values),
          status: 'planned', everCreated: false };
        data.records.push(record);
        return record;
      });
    },
    beginCreate(key) {
      prepare();
      return transact(data => {
        if (budget(data).pending) fail('unresolved pending save; reconcile it through the UI before any new creation.');
        const record = entry(data, key);
        if (record.everCreated) fail(`${key} was already created; reuse it or plan a different logical key.`);
        if (!budget(data).remaining) fail('the task creation limit is exhausted.');
        record.status = 'pending';
        return record;
      });
    },
    found(key, observed) {
      return transact(data => {
        const record = entry(data, key);
        if (!observed || !['string', 'number'].includes(typeof observed.id) || !String(observed.id).trim()
          || (typeof observed.id === 'number' && !Number.isFinite(observed.id))) fail('found requires an exact record id.');
        const details = { ...copy(observed), id: String(observed.id) };
        if (record.everCreated && record.observed.id !== details.id) fail(`observed id differs for ${key}.`);
        if (!record.everCreated && record.status !== 'pending') fail(`${key} has no pending creation to reconcile.`);
        record.everCreated = true;
        record.status = 'created';
        record.observed = { ...record.observed, ...details };
        return record;
      });
    },
    absent(key) {
      return transact(data => {
        const record = entry(data, key);
        if (record.status !== 'deleted') record.status = 'absent';
        return record;
      });
    },
    deleted(key) {
      return transact(data => {
        const record = entry(data, key);
        if (!record.everCreated) fail('reconcile a created record before recording its deletion.');
        record.status = 'deleted';
        return record;
      });
    },
    snapshot() { const data = read(); return { ...data, budget: budget(data) }; },
  };
}
