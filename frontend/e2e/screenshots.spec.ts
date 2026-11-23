import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * Screenshots for docs/UI_DEMO.md (1280×800 viewport). Runs only in the `screenshots` project:
 *   PW_CHANNEL=chrome npm run screenshots
 */
const outDir = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '..',
  '..',
  'docs',
  'figures',
  'ui',
);

const SCREENS: [string, string][] = [
  ['01-home', '/'],
  ['02-login', '/login'],
  ['03-register', '/register'],
  ['04-upload', '/upload'],
  ['05-result-oscc-suspected', '/result/case-a'],
  ['06-result-inconclusive', '/result/case-b'],
  ['07-result-non-oscc', '/result/case-c'],
  ['08-compare', '/compare?case=case-a'],
  ['09-hospitals', '/hospitals'],
  ['10-treatment', '/treatment'],
  ['11-admin', '/admin'],
  ['12-support', '/support'],
];

for (const [name, path] of SCREENS) {
  test(`screenshot ${name}`, async ({ page }) => {
    mkdirSync(outDir, { recursive: true });
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: resolve(outDir, `${name}.png`) });
  });
}
