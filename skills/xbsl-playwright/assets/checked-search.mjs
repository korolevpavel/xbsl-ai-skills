// Copy into the consumer project. search(query) must wait for THAT query's
// completed UI results and return their observed unique record IDs.
// Both records must use the same field and formatting in queryFor(record).
export async function expectAbsentBySearch({ known, candidate, queryFor, search }) {
  const controlQuery = queryFor(known);
  const candidateQuery = queryFor(candidate);
  if (typeof controlQuery !== 'string' || !controlQuery.trim()
      || typeof candidateQuery !== 'string' || !candidateQuery.trim()
      || controlQuery === candidateQuery || !known.id) {
    throw new Error('SEARCH: provide distinct non-empty queries and a known record ID.');
  }
  const control = await search(controlQuery);
  if (control.length !== 1 || control[0] !== known.id) {
    throw new Error(`SEARCH: positive control failed for ${JSON.stringify(controlQuery)}; absence is unverified.`);
  }
  const matches = await search(candidateQuery);
  if (matches.length !== 0) {
    throw new Error(`SEARCH: expected absence for ${JSON.stringify(candidateQuery)}, found ${JSON.stringify(matches)}.`);
  }
}
