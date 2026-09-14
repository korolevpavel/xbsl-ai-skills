import { test, expect, type Locator, type Page } from '@playwright/test';

// Temporary reconnaissance: copy into the consumer testDir, then remove it.
// ELEMENT_INSPECT_SELECTOR must identify one observed form or navigation area.
// This snapshot helps author locators; it is not acceptance evidence.
test.use({ trace: 'off', screenshot: 'off', video: 'off' });

async function appReady(page: Page, surface: Locator) {
  const password = page.locator('input[type="password"]:visible');
  const login = page.getByRole('heading', { name: /^(Sign in|Log in|Вход(?: в систему)?|Авторизация)$/i });
  await expect(surface.or(password).or(login).first()).toBeVisible();
  const authURL = /\/sys\/auth\/authorization\/?|\/auth\/(?:v\d+\/)?(?:server\/)?signin\/?/i.test(new URL(page.url()).pathname);
  if (authURL || await password.count() || await login.isVisible()) {
    throw new Error('AUTH: sign in before inspecting the application.');
  }
  await expect(surface).toHaveCount(1);
  await expect(surface).toBeVisible();
}

test('inspect UI for test authoring', async ({ page }) => {
  const url = process.env.ELEMENT_APP_URL;
  const selector = process.env.ELEMENT_INSPECT_SELECTOR;
  const readySelector = process.env.ELEMENT_READY_SELECTOR;
  if (!url || !selector || !readySelector) {
    throw new Error('Set ELEMENT_APP_URL, ELEMENT_READY_SELECTOR (observed initial content) and ELEMENT_INSPECT_SELECTOR.');
  }
  await page.goto(url);
  await appReady(page, page.locator(readySelector));

  // EDIT HERE: observed navigation, then await the exact target heading/content.
  // Keep appReady guards and the output limit. Menu visibility is not readiness.

  const surface = page.locator(selector);
  await appReady(page, surface);
  const snapshot = await surface.ariaSnapshot();
  const commands = process.env.ELEMENT_INSPECT_COMMANDS === '1'
    ? await surface.locator('[data-testid], button, [role="button"], [data-component="button"]')
      .evaluateAll(elements => elements
        .filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden')
        .slice(0, 41).map(el => ({
          tag: el.tagName.toLowerCase(), text: el.textContent?.trim().slice(0, 80),
          ...Object.fromEntries(['data-testid', 'data-component', 'aria-label', 'title', 'disabled', 'aria-disabled']
            .map(name => [name, el.getAttribute(name)]).filter(([, value]) => value !== null)),
        })))
    : [];
  const output = snapshot + (commands.length ? '\nCOMMANDS=' + JSON.stringify(commands) : '');
  if (commands.length > 40 || output.length > 8000) {
    throw new Error('Choose a narrower ELEMENT_INSPECT_SELECTOR (snapshot > 8000 characters).');
  }
  console.log(output);
});
