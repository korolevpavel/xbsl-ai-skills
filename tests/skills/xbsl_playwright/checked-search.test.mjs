import test from 'node:test';
import assert from 'node:assert/strict';
import { expectAbsentBySearch } from '../../../skills/xbsl-playwright/assets/checked-search.mjs';

const known = { id: 'doc-1', date: '2099-12-31', number: 'DOC-001' };
const candidate = { date: '2099-12-30' };

test('uses the same date format for the control and absence query', async () => {
  const queries = [];
  await expectAbsentBySearch({ known, candidate, queryFor: record => record.date,
    search: async query => { queries.push(query); return query === known.date ? [known.id] : []; },
  });
  assert.deepEqual(queries, [known.date, candidate.date]);
});

test('a search that misses the known record cannot prove absence', async () => {
  let calls = 0;
  await assert.rejects(expectAbsentBySearch({ known, candidate,
    queryFor: record => `${record.date} 23:49`,
    search: async () => { calls++; return []; },
  }), /positive control failed/);
  assert.equal(calls, 1);
});

test('a wrong or ambiguous control record is rejected', async () => {
  for (const control of [['another'], [known.id, 'another']]) {
    await assert.rejects(expectAbsentBySearch({ known, candidate,
      queryFor: record => record.date, search: async () => control,
    }), /positive control failed/);
  }
});

test('finds an erroneously saved candidate instead of declaring it absent', async () => {
  await assert.rejects(expectAbsentBySearch({ known, candidate,
    queryFor: record => record.date,
    search: async query => query === known.date ? [known.id] : ['doc-2'],
  }), /expected absence.*doc-2/);
});
