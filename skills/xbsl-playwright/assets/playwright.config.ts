import { randomUUID } from 'node:crypto';
import { existsSync } from 'node:fs';
import { defineConfig } from '@playwright/test';

// Copy only for a new, independent e2e package. Keep an existing config.
const appURL = process.env.ELEMENT_APP_URL;
if (!appURL) throw new Error('Set ELEMENT_APP_URL to the full application URL.');
if (!/^https?:$/.test(new URL(appURL).protocol)) throw new Error('ELEMENT_APP_URL must use HTTP(S).');
const authState = process.env.ELEMENT_AUTH_STATE ?? (existsSync('.auth/user.json') ? '.auth/user.json' : undefined);
const runID = process.env.ELEMENT_RUN_ID ||= randomUUID();
if (!/^[\w-]+$/.test(runID)) throw new Error('ELEMENT_RUN_ID: use letters, digits, _ or -.');

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  outputDir: `test-results/${runID}`,
  reporter: [
    ['list'],
    ['html', { outputFolder: `playwright-report/${runID}`, open: 'never' }],
  ],
  use: {
    browserName: 'chromium',
    baseURL: appURL,
    storageState: authState || undefined,
    launchOptions: { executablePath: process.env.ELEMENT_EXECUTABLE_PATH || undefined },
    trace: 'off',
    screenshot: 'only-on-failure',
    video: 'off',
  },
});
