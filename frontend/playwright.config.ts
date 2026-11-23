import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end click-through against the built site (`vite preview`). Run `npm run build` first.
 *
 * - CI: `npx playwright install --with-deps chromium` then `npm run test:e2e`.
 * - Local without downloading browsers: `PW_CHANNEL=chrome npm run test:e2e` uses the
 *   installed Google Chrome.
 * - Screenshots for docs/UI_DEMO.md: `PW_CHANNEL=chrome npm run screenshots` (writes
 *   ../docs/figures/ui/*.png).
 */
const PORT = 4173;
const channel = process.env.PW_CHANNEL;
const browser = {
  ...devices['Desktop Chrome'],
  viewport: { width: 1280, height: 800 },
  ...(channel ? { channel } : {}),
};

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    viewport: { width: 1280, height: 800 },
    trace: 'off',
  },
  projects: [
    {
      name: 'chromium',
      testIgnore: /screenshots\.spec\.ts/,
      use: { ...browser },
    },
    {
      name: 'screenshots',
      testMatch: /screenshots\.spec\.ts/,
      use: { ...browser },
    },
  ],
  webServer: {
    command: `npm run preview -- --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
