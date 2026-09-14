// Local workflow fixture, not a renderer or emulator of 1C:Element.
import http from 'node:http';
import { setTimeout as delay } from 'node:timers/promises';

const portIndex = process.argv.indexOf('--port');
const port = portIndex < 0 ? 0 : Number(process.argv[portIndex + 1]);
if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error('Expected --port 0..65535');
const vendors = ['North Supplies', 'River Trading'];
const products = ['Service package', 'Office supplies'];
const documents = new Map([['1', {
  id: '1', number: 'DOC-001', title: 'Example document', notes: 'Read-only example',
  vendor: vendors[0], product: products[0], price: 25.5, quantity: 2, discount: 10,
  total: 45.9, readOnly: true,
}]]);
let nextId = 2;
let totalCreated = 0;

const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Document fixture</title>
<style>body{font:17px system-ui;max-width:1050px;margin:2rem auto;padding:1rem}
label{display:block;margin:1rem 0}input,textarea,select,button{font:inherit}
input,textarea{min-width:280px}button{padding:.4rem;margin:.2rem}
table{border-collapse:collapse;width:100%;text-align:left}td,th{padding:.5rem;border-bottom:1px solid #ddd}
[role=alert]{color:#a00}#editor{position:fixed;bottom:1rem;right:1rem;padding:1rem;background:#eef;border:2px solid #339}
#editor[hidden]{display:none}#editor input{min-width:100px;width:150px}</style>
</head><body><main></main><script type="module">
const main = document.querySelector('main');
const params = new URLSearchParams(location.search);
const fault = params.get('fault');
const vendors = ${JSON.stringify(vendors)};
const products = ${JSON.stringify(products)};
const escape = value => String(value).replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = value => Number(value).toFixed(2);
const amount = row => Math.round(row.price * row.quantity * (1 - row.discount / 100) * 100) / 100;
async function api(path = '', options = {}, search) {
  const query = new URLSearchParams(params);
  if (search !== undefined) query.set('q', search);
  const response = await fetch('/api/documents' + path + '?' + query, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error);
  return result;
}
function error(message) { main.querySelector('[role="alert"]').textContent = message; }
async function list(message = '') {
  const records = await api();
  main.innerHTML = '<h1>Documents</h1><p role="status">' + escape(message) + '</p>' +
    '<p role="alert"></p><button type="button" id="new">New document</button>' +
    '<label>Search documents<input type="search" id="search"></label>' +
    '<section aria-label="Search results" aria-busy="false"><p role="status" id="search-status"></p>' +
    '<table><thead><tr><th>Number</th><th>Title</th><th>Notes</th><th>Total</th><th>Action</th></tr></thead>' +
    '<tbody></tbody></table></section>';
  main.querySelector('#new').onclick = () => form();
  const surface = main.querySelector('section');
  function render(found, query) {
    surface.querySelector('tbody').innerHTML = found.map(record =>
      '<tr data-document-id="' + record.id + '"><td>' + record.number + '</td><td>' +
      escape(record.title || '(Untitled)') + '</td><td>' + escape(record.notes) + '</td><td>' +
      money(record.total) + '</td><td><button type="button" data-open="' + record.id + '">Open</button></td></tr>').join('');
    surface.querySelector('#search-status').textContent = (query === undefined ? 'All documents' :
      'Results for "' + query + '"') + ': ' + found.length + ' documents';
    for (const button of surface.querySelectorAll('[data-open]')) button.onclick = async () => {
      try { form(await api('/' + button.dataset.open)); } catch (e) { error(e.message); }
    };
  }
  render(records);
  let revision = 0;
  main.querySelector('#search').oninput = async event => {
    const current = ++revision;
    const query = event.target.value;
    surface.setAttribute('aria-busy', 'true');
    surface.querySelector('#search-status').textContent = 'Searching...';
    try {
      const found = await api('', {}, query);
      if (current === revision && surface.isConnected) {
        render(found, query); surface.setAttribute('aria-busy', 'false');
      }
    } catch (e) { if (surface.isConnected) error(e.message); }
  };
}
function form(record = {}) {
  const row = {price: record.price ?? 0, quantity: record.quantity ?? 0, discount: record.discount ?? 0};
  const columns = ['price', 'quantity', 'discount'];
  const labels = {price: 'Price', quantity: 'Quantity', discount: 'Discount'};
  main.innerHTML = '<h1>' + (record.readOnly ? 'View document' : record.id ? 'Edit document' : 'New document') + '</h1>' +
    '<p data-testid="document-number">' + (record.number ?? 'Not saved') + '</p>' +
    (record.readOnly ? '<p>This example is read-only.</p>' : '') +
    '<form novalidate><p role="alert"></p><label>Title<input name="title" required value="' + escape(record.title ?? '') + '"></label>' +
    '<label>Notes<textarea name="notes">' + escape(record.notes ?? '') + '</textarea></label>' +
    '<label>Vendor<select name="vendor" required><option value="">Choose vendor</option>' +
    vendors.map(value => '<option' + (value === record.vendor ? ' selected' : '') + '>' + value + '</option>').join('') +
    '</select></label><p role="status" id="vendor-status"></p>' +
    '<table aria-label="Document lines"><thead><tr><th>Product</th><th>Price</th><th>Quantity</th><th>Discount, %</th><th>Total</th></tr></thead>' +
    '<tbody><tr><td><select name="product" aria-label="Product"><option value="">Choose product</option>' +
    products.map(value => '<option' + (value === record.product ? ' selected' : '') + '>' + value + '</option>').join('') +
    '</select></td>' + columns.map(column => '<td><button type="button" data-testid="line-' + column + '" data-column="' + column + '"></button></td>').join('') +
    '<td data-testid="line-total"></td></tr></tbody></table>' +
    '<p>Click a numeric cell to edit. Enter commits; Tab commits and moves to the next numeric cell.</p>' +
    '<div id="editor" role="region" aria-label="Active cell editor" hidden><label><span id="editor-label"></span>' +
    '<input inputmode="decimal" id="cell-value" aria-label="Cell value"></label>' +
    '<button type="button" id="commit">Apply cell value</button></div>' +
    '<button type="submit"' + (record.readOnly ? ' disabled' : '') + '>Save</button>' +
    '<button type="button" id="close">Close</button></form>';
  const editor = main.querySelector('#editor');
  const input = main.querySelector('#cell-value');
  let activeColumn;
  function draw() {
    for (const column of columns) main.querySelector('[data-column="' + column + '"]').textContent = labels[column] + ': ' + money(row[column]);
    main.querySelector('[data-testid="line-total"]').textContent = money(amount(row));
  }
  function commit() {
    if (!activeColumn) return true;
    const value = Number(input.value.trim().replace(',', '.'));
    if (!input.value.trim() || !Number.isFinite(value) || value < 0 || (activeColumn === 'discount' && value > 100)) {
      error(labels[activeColumn] + ' must be a valid nonnegative number' + (activeColumn === 'discount' ? ' from 0 to 100' : ''));
      return false;
    }
    row[activeColumn] = value; draw(); error(''); return true;
  }
  function activate(column) {
    if (!commit()) return;
    activeColumn = column; editor.hidden = false;
    main.querySelector('#editor-label').textContent = labels[column];
    input.setAttribute('aria-label', labels[column]);
    input.value = money(row[column]); input.focus(); input.select();
  }
  function finish() {
    if (!commit()) return false;
    activeColumn = undefined; editor.hidden = true; return true;
  }
  for (const button of main.querySelectorAll('[data-column]')) {
    button.disabled = Boolean(record.readOnly);
    button.onclick = () => activate(button.dataset.column);
  }
  input.onkeydown = event => {
    if (event.key === 'Enter') { event.preventDefault(); finish(); }
    if (event.key === 'Tab') {
      event.preventDefault();
      const index = (columns.indexOf(activeColumn) + (event.shiftKey ? 2 : 1)) % columns.length;
      activate(columns[index]);
    }
    if (event.key === 'Escape') { activeColumn = undefined; editor.hidden = true; }
  };
  main.querySelector('#commit').onclick = finish;
  main.querySelector('#close').onclick = () => list();
  const vendor = main.querySelector('[name="vendor"]');
  vendor.onchange = () => {
    main.querySelector('#vendor-status').textContent = vendor.value ? 'Vendor selected: ' + vendor.value : 'No vendor selected';
  };
  vendor.onchange(); draw();
  if (record.readOnly) for (const field of main.querySelectorAll('input,textarea,select')) field.disabled = true;
  main.querySelector('form').onsubmit = async event => {
    event.preventDefault();
    if (record.readOnly || !finish()) return;
    const fields = Object.fromEntries(new FormData(event.target));
    if (!['allow-missing-title', 'invalid-with-error'].includes(fault) && !fields.title.trim()) { error('Title is required'); return; }
    if (!vendors.includes(fields.vendor)) { error('Vendor is required'); return; }
    if (!products.includes(fields.product)) { error('Product is required'); return; }
    try {
      await api(record.id ? '/' + record.id : '', {
        method: record.id ? 'PUT' : 'POST', headers: {'content-type': 'application/json'},
        body: JSON.stringify({...fields, ...row}),
      });
      await list('Document saved');
    } catch (e) { error(e.message); }
  };
}
await list();
</script></body></html>`;

function json(response, status, value) {
  response.writeHead(status, {'content-type': 'application/json', 'cache-control': 'no-store'});
  response.end(JSON.stringify(value));
}
const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, 'http://127.0.0.1');
  if (request.method === 'GET' && url.pathname === '/') {
    response.writeHead(200, {'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store'});
    response.end(html); return;
  }
  if (request.method === 'GET' && url.pathname === '/__fixture__/records') {
    const prefix = url.searchParams.get('prefix');
    const records = [...documents.values()].filter(record => !prefix || record.title.startsWith(prefix) || record.notes.startsWith(prefix));
    json(response, 200, {totalCreated, count: records.length, records}); return;
  }
  const match = /^\/api\/documents(?:\/(\d+))?$/.exec(url.pathname);
  if (!match) { json(response, 404, {error: 'Not found'}); return; }
  const id = match[1];
  const fault = url.searchParams.get('fault');
  if (id && !documents.has(id)) { json(response, 404, {error: 'Document not found'}); return; }
  if (request.method === 'GET') {
    if (id) { json(response, 200, documents.get(id)); return; }
    const search = url.searchParams.get('q');
    if (search !== null) await delay(400);
    const found = [...documents.values()].filter(record => search === null || (fault !== 'search-miss' &&
      (record.number + '\n' + record.title + '\n' + record.notes).toLowerCase().includes(search.toLowerCase())));
    json(response, 200, found); return;
  }
  if ((request.method === 'POST' && !id) || (request.method === 'PUT' && id)) {
    if (id && documents.get(id).readOnly) { json(response, 403, {error: 'Example document is read-only'}); return; }
    try {
      let body = '';
      for await (const chunk of request) {
        body += chunk;
        if (body.length > 16384) { json(response, 413, {error: 'Body too large'}); return; }
      }
      const data = JSON.parse(body);
      if (typeof data.title !== 'string' || (!['allow-missing-title', 'invalid-with-error'].includes(fault) && !data.title.trim())) {
        json(response, 400, {error: 'Title is required'}); return;
      }
      if (typeof data.notes !== 'string' || !vendors.includes(data.vendor) || !products.includes(data.product)) {
        json(response, 400, {error: 'Notes, a known Vendor and a known Product are required'}); return;
      }
      if (![data.price, data.quantity, data.discount].every(value => typeof value === 'number' && Number.isFinite(value) && value >= 0) || data.discount > 100) {
        json(response, 400, {error: 'Invalid numeric line values'}); return;
      }
      const savedId = id ?? String(nextId++);
      const quantity = fault === 'discard-quantity' ? 0 : data.quantity;
      const record = {
        id: savedId, number: 'DOC-' + savedId.padStart(3, '0'), title: data.title, notes: data.notes,
        vendor: data.vendor, product: data.product, price: data.price, quantity, discount: data.discount,
        total: Math.round(data.price * quantity * (1 - data.discount / 100) * 100) / 100, readOnly: false,
      };
      documents.set(savedId, record);
      if (!id) totalCreated++;
      if (fault === 'invalid-with-error' && !data.title.trim()) {
        json(response, 400, {error: 'Title is required'}); return;
      }
      if (!id && fault === 'accept-then-error') {
        json(response, 503, {error: 'Save result unavailable. Check the document list before trying again.'}); return;
      }
      json(response, id ? 200 : 201, {id: savedId, number: record.number, message: 'Document saved'});
    } catch { json(response, 400, {error: 'Invalid JSON'}); }
    return;
  }
  json(response, 405, {error: 'Method not allowed'});
});
server.listen(port, '127.0.0.1', () => console.log('http://127.0.0.1:' + server.address().port + '/'));
