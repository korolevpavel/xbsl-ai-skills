import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { openTestData } from '../../../skills/xbsl-playwright/assets/test-data.mjs';

const helperURL = new URL('../../../skills/xbsl-playwright/assets/test-data.mjs', import.meta.url).href;
const options = { appURL: 'https://example.invalid/applications/demo?revision=1', maxCreated: 3, retention: 'keep' };

function fixture(t) {
  const directory = mkdtempSync(join(tmpdir(), 'xbsl-test-data-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const file = join(directory, '.test-data', 'task.json');
  return { directory, file, prepare: () => openTestData(file, { ...options, mode: 'prepare' }) };
}

function childScript(body) {
  return `import { openTestData } from ${JSON.stringify(helperURL)};
const data = openTestData(process.argv[1], ${JSON.stringify({ ...options, mode: 'prepare' })});
${body}`;
}

test('logical values and markers persist across processes and run IDs', t => {
  const { file } = fixture(t);
  const first = spawnSync(process.execPath, ['--input-type=module', '-e', childScript(`
data.record('client', {name:'Example', amount:1000, discount:10});
data.beginCreate('client'); data.found('client', {id:'client-17'});
console.log(JSON.stringify(data.snapshot()));`), file], { env: { ...process.env, ELEMENT_RUN_ID: 'first' }, encoding: 'utf8' });
  assert.equal(first.status, 0, first.stderr);
  const second = spawnSync(process.execPath, ['--input-type=module', '-e', `
import { openTestData } from ${JSON.stringify(helperURL)};
console.log(JSON.stringify(openTestData(process.argv[1], ${JSON.stringify(options)}).snapshot()));`, file],
  { env: { ...process.env, ELEMENT_RUN_ID: 'repair' }, encoding: 'utf8' });
  assert.equal(second.status, 0, second.stderr);
  assert.deepEqual(JSON.parse(second.stdout), JSON.parse(first.stdout));
  const data = openTestData(file, options);
  const record = data.record('client');
  record.values.amount = 0;
  record.marker = 'changed';
  assert.equal(data.record('client').values.amount, 1000);
  assert.notEqual(data.record('client').marker, 'changed');
  assert.throws(() => data.record('client', { name: 'Example', amount: 0, discount: 10 }), /expected values differ/);
});

test('verify never creates a missing task, new logical key or reservation', t => {
  const { file, prepare } = fixture(t);
  assert.throws(() => openTestData(file, options), /forbidden in verify/);
  assert.equal(existsSync(dirname(file)), false);
  const creator = prepare();
  creator.record('client', { amount: 1000 });
  const before = readFileSync(file, 'utf8');
  const verify = openTestData(file, options);
  assert.equal(verify.record('client').status, 'planned');
  assert.throws(() => verify.record('document', {}), /forbidden in verify/);
  assert.throws(() => verify.beginCreate('client'), /forbidden in verify/);
  assert.throws(() => verify.found('client', { id: 'unreserved' }), /no pending creation/);
  assert.equal(readFileSync(file, 'utf8'), before);
  rmSync(file);
  assert.throws(() => creator.record('client', { amount: 1000 }), /disappeared/);
  assert.equal(existsSync(file), false);
});

test('all created records and pending reservations share the lifetime limit', t => {
  const { prepare } = fixture(t);
  const data = prepare();
  for (const key of ['client', 'document', 'invalid-form', 'extra']) data.record(key, { name: key });
  data.beginCreate('client'); data.found('client', { id: '1' }); data.deleted('client');
  data.beginCreate('document'); data.found('document', { id: '2' });
  data.beginCreate('invalid-form');
  assert.deepEqual(data.snapshot().budget, { created: 2, pending: 1, remaining: 0 });
  assert.throws(() => data.beginCreate('extra'), /pending save/);
  data.absent('invalid-form');
  assert.deepEqual(data.snapshot().budget, { created: 2, pending: 0, remaining: 1 });
  data.beginCreate('extra'); data.found('extra', { id: '3' }); data.deleted('extra');
  assert.deepEqual(data.snapshot().budget, { created: 3, pending: 0, remaining: 0 });
  assert.throws(() => data.beginCreate('invalid-form'), /limit is exhausted/);
  assert.equal(data.snapshot().records.length, 4);
});

test('a terminated creator leaves pending durable and blocks later creates until reconciliation', t => {
  const { file, prepare } = fixture(t);
  const initial = prepare();
  initial.record('client', { name: 'Example' }); initial.record('document', {});
  const crashed = spawnSync(process.execPath, ['--input-type=module', '-e',
    childScript("data.beginCreate('client'); process.exit(17);"), file]);
  assert.equal(crashed.status, 17);
  const restarted = prepare();
  assert.equal(restarted.record('client').status, 'pending');
  assert.throws(() => restarted.beginCreate('client'), /pending save/);
  assert.throws(() => initial.beginCreate('document'), /pending save/); // An old handle must reread disk.
  restarted.absent('document');
  assert.throws(() => restarted.beginCreate('document'), /pending save/);
  openTestData(file, options).absent('client'); // Read-only UI reconciliation is allowed in verify.
  restarted.beginCreate('document');
  assert.equal(restarted.snapshot().budget.pending, 1);
});

test('observed identity is stable, confirmation is idempotent, absence/deletion never allow recreation', t => {
  const { file, prepare } = fixture(t);
  const data = prepare();
  data.record('client', { amount: 1000 }); data.beginCreate('client');
  const verify = openTestData(file, options);
  verify.found('client', { id: 'id-1', url: '/old', amount: 1000 });
  verify.found('client', { id: 'id-1', url: '/new' });
  assert.equal(verify.snapshot().budget.created, 1);
  assert.equal(verify.record('client').observed.amount, 1000);
  assert.equal(verify.record('client').observed.url, '/new');
  assert.throws(() => verify.found('client', { id: 'id-2' }), /id differs/);
  verify.absent('client');
  assert.equal(verify.snapshot().budget.created, 1);
  assert.throws(() => data.beginCreate('client'), /already created/);
  verify.deleted('client'); verify.absent('client');
  assert.equal(verify.record('client').status, 'deleted');
  assert.equal(verify.snapshot().budget.created, 1);
  assert.throws(() => data.beginCreate('client'), /already created/);
});

test('full application URL, limit and retention cannot reset an existing task', t => {
  const { file, prepare } = fixture(t);
  const data = prepare(); data.record('client', {}); data.beginCreate('client');
  const before = readFileSync(file, 'utf8');
  for (const changed of [
    { appURL: 'https://example.invalid/applications/another?revision=1' },
    { appURL: 'https://example.invalid/applications/demo?revision=2' },
    { maxCreated: 4 }, { retention: 'cleanup' },
  ]) assert.throws(() => openTestData(file, { ...options, ...changed, mode: 'prepare' }), /differs/);
  assert.equal(readFileSync(file, 'utf8'), before);
});

test('independent processes cannot both reserve the remaining slot', async t => {
  const { file, prepare } = fixture(t);
  const data = prepare();
  for (const key of ['used-1', 'used-2', 'a', 'b']) data.record(key, {});
  for (const key of ['used-1', 'used-2']) { data.beginCreate(key); data.found(key, { id: key }); }
  const run = key => new Promise(resolve => {
    const child = spawn(process.execPath, ['--input-type=module', '-e', childScript(`
try { data.beginCreate(${JSON.stringify(key)}); } catch { process.exitCode=1; }`), file], { stdio: 'ignore' });
    child.on('close', resolve);
  });
  const outcomes = await Promise.all([run('a'), run('b')]);
  assert.deepEqual(outcomes.sort(), [0, 1]);
  assert.deepEqual(data.snapshot().budget, { created: 2, pending: 1, remaining: 0 });
});

test('corrupt state and an existing lock fail without resetting data or removing the lock', t => {
  const { file, prepare } = fixture(t);
  const data = prepare(); data.record('client', {});
  const original = readFileSync(file, 'utf8');
  const lock = `${file}.lock`;
  writeFileSync(lock, 'another-or-interrupted-process');
  assert.throws(() => data.beginCreate('client'), /locked/);
  assert.equal(readFileSync(lock, 'utf8'), 'another-or-interrupted-process');
  assert.equal(readFileSync(file, 'utf8'), original);
  rmSync(lock);
  const invalid = [
    '{broken JSON',
    JSON.stringify({ ...JSON.parse(original), version: 99 }),
    JSON.stringify({ ...JSON.parse(original), records: [{ ...JSON.parse(original).records[0], everCreated: true }] }),
    JSON.stringify({ ...JSON.parse(original), records: Array(2).fill(JSON.parse(original).records[0]) }),
  ];
  for (const content of invalid) {
    writeFileSync(file, content);
    assert.throws(() => prepare());
    assert.equal(readFileSync(file, 'utf8'), content);
  }
});

test('non-JSON expected values are rejected and unusual logical keys remain ordinary records', t => {
  const { prepare } = fixture(t);
  const data = prepare();
  for (const values of [{ amount: NaN }, { amount: Infinity }, { name: undefined }, { callback: () => 1 }]) {
    assert.throws(() => data.record('invalid', values), /exact JSON data/);
  }
  assert.equal(data.snapshot().records.length, 0);
  for (const key of ['__proto__', 'constructor']) data.record(key, { amount: 1000 });
  assert.equal(data.record('__proto__').values.amount, 1000);
  assert.equal(data.snapshot().records.length, 2);
});
