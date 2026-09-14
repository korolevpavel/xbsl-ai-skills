// Deterministic browser fixture. This is not a renderer or emulator of 1C:Element.
import http from 'node:http';
import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';

const portIndex = process.argv.indexOf('--port');
const port = portIndex < 0 ? 0 : Number(process.argv[portIndex + 1]);
if (!Number.isInteger(port) || port < 0 || port > 65535) {
  throw new Error('Expected --port 0..65535');
}
const records = new Map();
const sessions = new Set();
let nextId = 1;

const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Record fixture</title>
<style>body{font:18px system-ui;max-width:800px;margin:3rem auto;padding:1rem}
label{display:block;margin:1rem 0}input,textarea,button{font:inherit}
input,textarea,select{display:block;width:95%}button{margin:.3rem;padding:.4rem}
table{width:100%;text-align:left}th,td{padding:.5rem} [role=alert]{color:#a00}</style>
</head><body><main></main><script type="module">
const main = document.querySelector('main');
const query = location.search;
const params = new URLSearchParams(query);
const adversarial = params.get('mode') === 'adversarial';
const fault = params.get('fault');
const escape = value => String(value).replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path = '', options = {}, search) {
  const filter = new URLSearchParams(params);
  if (search !== undefined) filter.set('q', search);
  const response = await fetch('/api/records' + path + '?' + filter, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error);
  return result;
}
function error(message) {
  main.querySelector('[role="alert"]').textContent = message;
}
async function list(message = '') {
  const records = await api();
  main.innerHTML = '<h1>Records</h1><p role="status">' + escape(message) + '</p>' +
    '<p role="alert"></p><button type="button" id="new">New record</button>' +
    (adversarial ? '<label>Search records<input type="search" id="search"></label>' : '') +
    '<section aria-label="Search results" aria-busy="false">' +
    (adversarial ? '<p role="status" id="search-status"></p>' : '') +
    '<table><thead><tr><th>Name</th>' +
    (adversarial ? '<th>Code</th><th>Category</th><th>Notes</th>' : '') +
    '<th>Action</th></tr></thead><tbody></tbody></table></section>';
  main.querySelector('#new').onclick = () => form();
  const surface = main.querySelector('section');
  function render(found, search = '') {
    surface.querySelector('tbody').innerHTML = found.map(record =>
      '<tr><td>' + escape(record.name) + '</td>' + (adversarial ?
      '<td>' + record.id + '</td><td>' + escape(record.category) + '</td><td>' + escape(record.notes) + '</td>' : '') +
      '<td><button type="button" data-id="' + record.id + '">Open</button></td></tr>').join('');
    if (adversarial) surface.querySelector('#search-status').textContent =
      (search ? 'Results for "' + search + '"' : 'All records') + ': ' + found.length + ' records';
    for (const button of surface.querySelectorAll('[data-id]')) button.onclick = async () => {
      try { form(await api('/' + button.dataset.id)); } catch (e) { error(e.message); }
    };
  }
  render(records);
  let revision = 0;
  if (adversarial) main.querySelector('#search').oninput = async event => {
    const current = ++revision;
    const search = event.target.value;
    surface.setAttribute('aria-busy', 'true');
    surface.querySelector('#search-status').textContent = 'Searching...';
    try {
      const found = await api('', {}, search);
      if (current === revision && surface.isConnected) {
        render(found, search);
        surface.setAttribute('aria-busy', 'false');
      }
    } catch (e) { if (surface.isConnected) error(e.message); }
  };
}
function form(record = {}) {
  main.innerHTML = '<h1>' + (record.id ? 'Edit record' : 'New record') + '</h1>' +
    '<form novalidate><p role="alert"></p>' +
    '<label>Name<input name="name" required value="' + escape(record.name ?? '') + '"></label>' +
    (adversarial ? '<label>Category<select name="category" required>' +
      ['', 'Standard', 'Priority'].map(value => '<option value="' + value + '"' +
        (value === (record.category ?? '') ? ' selected' : '') + '>' + (value || 'Choose category') + '</option>').join('') +
      '</select></label>' : '') +
    '<label>Notes<textarea name="notes">' + escape(record.notes ?? '') + '</textarea></label>' +
    '<button type="submit">Save</button><button type="button" id="close">Close</button>' +
    (record.id ? '<button type="button" id="delete">Delete</button>' : '') + '</form>';
  main.querySelector('#close').onclick = () => list();
  main.querySelector('form').onsubmit = async event => {
    event.preventDefault();
    const fields = new FormData(event.target);
    if (fault !== 'allow-missing-name' && !String(fields.get('name')).trim()) {
      error('Name is required'); return;
    }
    if (adversarial && fault !== 'allow-missing-category' && !fields.get('category')) {
      error('Category is required'); return;
    }
    try {
      await api(record.id ? '/' + record.id : '', {
        method: record.id ? 'PUT' : 'POST',
        headers: {'content-type': 'application/json'},
        body: JSON.stringify(Object.fromEntries(fields)),
      });
      await list('Record saved');
    } catch (e) { error(e.message); }
  };
  if (record.id) main.querySelector('#delete').onclick = async () => {
    try { await api('/' + record.id, {method: 'DELETE'}); await list('Record deleted'); }
    catch (e) { error(e.message); }
  };
}
function login() {
  main.innerHTML = '<h1>Sign in</h1><p>Local fixture: no password or real account required.</p>' +
    '<form><p role="alert"></p><label>Demo user<input name="user" value="fixture-user" required></label>' +
    '<button type="submit">Sign in</button></form>';
  main.querySelector('form').onsubmit = async event => {
    event.preventDefault();
    const response = await fetch('/api/session', {method: 'POST'});
    if (response.ok) await list(); else error('Sign in failed');
  };
}
if (params.get('auth') === 'expired') {
  main.innerHTML = '<h1>Sign in</h1><p role="alert">Your session has expired.</p>' +
    '<label>Email<input type="email"></label><button disabled>Sign in</button>';
} else if (params.get('auth') === 'cookie' && !(await fetch('/api/session')).ok) {
  login();
} else {
  await list();
}
</script></body></html>`;

function json(response, status, value) {
  response.writeHead(status, {'content-type': 'application/json', 'cache-control': 'no-store'});
  response.end(JSON.stringify(value));
}

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, 'http://127.0.0.1');
  const session = /(?:^|;\s*)fixture_session=([^;]+)/.exec(request.headers.cookie ?? '')?.[1];
  if (url.pathname === '/api/session') {
    if (request.method === 'POST') {
      const token = randomUUID();
      sessions.add(token);
      response.setHeader('set-cookie', 'fixture_session=' + token + '; HttpOnly; SameSite=Strict; Path=/');
      json(response, 200, {signedIn: true}); return;
    }
    if (request.method === 'GET') {
      json(response, sessions.has(session) ? 200 : 401, {signedIn: sessions.has(session)}); return;
    }
    json(response, 405, {error: 'Method not allowed'}); return;
  }
  if (url.pathname === '/__fixture__/records' && request.method === 'GET') {
    const prefix = url.searchParams.get('prefix');
    if (!prefix?.startsWith('E2E-')) {
      json(response, 400, {error: 'An E2E- prefix is required'}); return;
    }
    const own = [...records.values()].filter(record =>
      record.name.startsWith(prefix) || record.notes.startsWith(prefix));
    json(response, 200, {count: own.length, records: own.map(({id, name}) => ({id, name}))}); return;
  }
  if (request.method === 'GET' && url.pathname === '/') {
    response.writeHead(200, {'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store'});
    response.end(html);
    return;
  }
  const match = /^\/api\/records(?:\/(\d+))?$/.exec(url.pathname);
  if (!match) { json(response, 404, {error: 'Not found'}); return; }
  if (url.searchParams.get('auth') === 'expired' ||
      (url.searchParams.get('auth') === 'cookie' && !sessions.has(session))) {
    json(response, 401, {error: 'Session expired'}); return;
  }
  const id = match[1];
  if (id && !records.has(id)) { json(response, 404, {error: 'Record not found'}); return; }
  if (request.method === 'GET') {
    const search = url.searchParams.get('q');
    if (!id && url.searchParams.get('mode') === 'adversarial' && search !== null) await delay(450);
    const found = [...records.values()].filter(record => !search ||
      (record.name + '\n' + record.notes).toLowerCase().includes(search.toLowerCase()));
    json(response, 200, id ? records.get(id) : found); return;
  }
  if (request.method === 'DELETE' && id) {
    records.delete(id); json(response, 200, {deleted: id}); return;
  }
  if ((request.method === 'POST' && !id) || (request.method === 'PUT' && id)) {
    try {
      let body = '';
      for await (const chunk of request) {
        body += chunk;
        if (body.length > 16384) { json(response, 413, {error: 'Body too large'}); return; }
      }
      const data = JSON.parse(body);
      const fault = url.searchParams.get('fault');
      if (typeof data.name !== 'string' || (fault !== 'allow-missing-name' && !data.name.trim())) {
        json(response, 400, {error: 'Name is required'}); return;
      }
      if (url.searchParams.get('mode') === 'adversarial' &&
          fault !== 'allow-missing-category' && !['Standard', 'Priority'].includes(data.category)) {
        json(response, 400, {error: 'Category is required'}); return;
      }
      if (typeof data.notes !== 'string') {
        json(response, 400, {error: 'Notes must be text'}); return;
      }
      const record = {
        id: id ?? String(nextId++), name: data.name,
        category: typeof data.category === 'string' ? data.category : '',
        notes: fault === 'discard-save' ? '' : data.notes,
      };
      records.set(record.id, record);
      json(response, id ? 200 : 201, {id: record.id, message: 'Record saved'});
    } catch { json(response, 400, {error: 'Invalid JSON'}); }
    return;
  }
  json(response, 405, {error: 'Method not allowed'});
});
server.listen(port, '127.0.0.1', () => {
  console.log('http://127.0.0.1:' + server.address().port + '/');
});
