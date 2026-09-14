import { randomUUID } from 'node:crypto';
import { mkdir, rename, rm, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { createInterface } from 'node:readline/promises';
import { chromium } from '@playwright/test';

let phase = 'configuration';
const reject = (message) => { throw Object.assign(new Error(message), { safe: true }); };
const loginHeading = /^(Sign in|Log in|Login|Вход(?: в систему)?|Авторизация|Аутентификация)$/i;

async function isLogin(page) {
  return /\/sys\/auth\/authorization\/?|\/auth\/(?:v\d+\/)?(?:server\/)?signin\/?/i.test(new URL(page.url()).pathname)
    || await page.locator('input[type="password"]:visible').count() > 0
    || await page.getByRole('heading', { name: loginHeading }).count() > 0;
}

async function open(page, url) {
  const response = await page.goto(url);
  if (response && response.status() >= 400) reject(`ENVIRONMENT: application returned HTTP ${response.status()}.`);
}

async function main() {
  const rawURL = process.env.ELEMENT_APP_URL;
  let url;
  try { url = new URL(rawURL); } catch { reject('Set ELEMENT_APP_URL to the full application URL.'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
    reject('ELEMENT_APP_URL must use HTTP(S), without embedded credentials.');
  }
  const checkOnly = process.argv.includes('--check');
  if (process.argv.slice(2).some((arg) => arg !== '--check')) reject('Only --check is supported.');
  let selector = process.env.ELEMENT_READY_SELECTOR;
  if (checkOnly && !selector) reject('Set an observed ELEMENT_READY_SELECTOR to check the saved session.');
  const state = resolve(process.env.ELEMENT_AUTH_STATE || '.auth/user.json');
  phase = 'launch Chromium';
  const browser = await chromium.launch({ headless: checkOnly,
    executablePath: process.env.ELEMENT_EXECUTABLE_PATH || undefined,
  }).catch((error) => {
    if (/Executable doesn't exist/.test(error.message)) reject('ENVIRONMENT: Chromium is missing. Run npm exec -- playwright install chromium once, then retry.');
    reject(`ENVIRONMENT: cannot launch Chromium (${error.name}). Check ELEMENT_EXECUTABLE_PATH and browser dependencies.`);
  });
  try {
    if (!checkOnly) {
      phase = 'open the application for manual sign-in';
      const context = await browser.newContext();
      const page = await context.newPage();
      await open(page, url.href);
      const input = createInterface({ input: process.stdin, output: process.stdout });
      const cancellation = new AbortController();
      const cancel = () => cancellation.abort();
      input.once('close', cancel);
      input.once('SIGINT', cancel);
      process.once('SIGINT', cancel);
      try {
        await input.question('Войдите в приложение. Дождитесь рабочей страницы и нажмите Enter здесь; браузер не закрывайте.\n', { signal: cancellation.signal });
      } catch (error) {
        if (error.name === 'AbortError') reject('AUTH CANCELLED: login was not confirmed; session was not saved.');
        throw error;
      } finally { process.removeListener('SIGINT', cancel); input.close(); }
      if (await isLogin(page)) reject('AUTH: the application still shows sign-in. Complete login before saving.');
      if (selector) {
        phase = 'wait for the observed application element';
        await page.locator(selector).waitFor({ state: 'visible' });
      } else {
        const headings = page.locator('h1:visible');
        if (await headings.count() === 1) {
          const title = (await headings.innerText()).replace(/\s+/g, ' ').trim();
          // Element may render H1 > SPAN: :text-is on H1 misses that nested text.
          if (title && !loginHeading.test(title)) selector = `role=heading[name=${JSON.stringify(title)}s]`;
        }
      }
      phase = 'save the session while its context is open';
      await mkdir(dirname(state), { recursive: true, mode: 0o700 });
      const temporary = `${state}.${randomUUID()}.tmp`;
      try {
        await writeFile(temporary, '', { flag: 'wx', mode: 0o600 });
        await context.storageState({ path: temporary, indexedDB: true });
        await rename(temporary, state);
      } finally { await rm(temporary, { force: true }); }
      await context.close();
      console.log('Session saved locally.');
      if (!selector) {
        reject('AUTH UNVERIFIED: set an observed ELEMENT_READY_SELECTOR and run npm run auth:check. No new login is needed.');
      }
    }
    phase = 'verify the saved session in a fresh context';
    const verification = await browser.newContext({ storageState: state });
    const page = await verification.newPage();
    await open(page, url.href);
    await page.locator(selector).waitFor({ state: 'visible' });
    if (await isLogin(page)) reject('AUTH: saved session returned to sign-in.');
    console.log('AUTH PASS: application element is visible in a fresh context.');
    console.log(`ELEMENT_READY_SELECTOR=${selector}`);
    await verification.close();
  } finally { await browser.close(); }
}

main().catch((error) => {
  // Raw browser errors may contain authorization URLs or fragments of state.
  console.error(error.safe ? error.message : `AUTH FAILED: ${phase} (${error.name}${error.code ? `, ${error.code}` : ''}).`);
  process.exitCode = 1;
});
