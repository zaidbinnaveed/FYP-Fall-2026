import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { strings } from '../src/strings';

async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'])
    .analyze();
  const summary = results.violations.map(
    (v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(' ')).join('; ')})`,
  );
  expect(summary).toEqual([]);
}

async function expectDemoBanner(page: Page) {
  await expect(page.getByText(strings.demoBanner)).toBeVisible();
}

test('main flow: login → sample case → result → hospitals → support (axe on every page)', async ({
  page,
}) => {
  await page.goto('/');
  await expectDemoBanner(page);
  await expectNoAxeViolations(page);

  await page.getByRole('link', { name: strings.homeStart }).click();
  await expect(page.getByRole('heading', { level: 1, name: strings.loginHeading })).toBeVisible();
  await expectNoAxeViolations(page);
  await page.getByLabel(strings.emailLabel).fill('demo@example.com');
  await page.getByLabel(strings.passwordLabel).fill('anything');
  await page.getByRole('button', { name: strings.loginSubmit }).click();

  await expect(page.getByRole('heading', { level: 1, name: strings.uploadHeading })).toBeVisible();
  await expect(page.getByText(strings.signedInAs('demo@example.com'))).toBeVisible();
  await expectDemoBanner(page);
  await expectNoAxeViolations(page);
  await page.getByRole('link', { name: 'Use Sample case A' }).click();

  await expect(page.getByRole('heading', { level: 1, name: strings.resultHeading })).toBeVisible();
  await expect(
    page.getByRole('heading', { level: 2, name: strings.outcomeLabel.oscc_suspected }),
  ).toBeVisible();
  await expect(page.getByText(strings.outcomeText.oscc_suspected)).toBeVisible();
  await expect(page.getByText(strings.disclaimer)).toBeVisible();
  await expectDemoBanner(page);
  await expectNoAxeViolations(page);
  await page.getByRole('link', { name: strings.findHospitalsPrompt }).click();

  await expect(
    page.getByRole('heading', { level: 1, name: strings.hospitalsHeading }),
  ).toBeVisible();
  await expect(page.getByRole('heading', { level: 2, name: 'Demo Hospital A' })).toBeVisible();
  await expect(page.getByText(strings.distanceLabel('2.4'))).toBeVisible();
  await expectDemoBanner(page);
  await expectNoAxeViolations(page);
  await page.getByRole('link', { name: strings.continueToSupport }).click();

  await expect(page.getByRole('heading', { level: 2, name: strings.chatbotHeading })).toBeVisible();
  await expect(page.getByText(strings.disclaimer)).toBeVisible();
  await expect(page.getByRole('textbox')).toHaveCount(0);
  await expectDemoBanner(page);
  await expectNoAxeViolations(page);
});

test('upload a file: the file name picks a sample case and nothing is analysed', async ({
  page,
}) => {
  await page.goto('/upload');
  await page.getByLabel(strings.uploadFileLabel).setInputFiles({
    name: 'slide_001.png',
    mimeType: 'image/png',
    buffer: Buffer.from('not really an image'),
  });
  await page.getByRole('button', { name: strings.uploadSubmit }).click();
  await expect(page.getByText(/the file "slide_001\.png" was not analysed/)).toBeVisible();
  await expect(page.getByText(strings.disclaimer)).toBeVisible();
  await expectNoAxeViolations(page);
});

for (const path of [
  '/compare?case=case-b',
  '/treatment',
  '/admin',
  '/register',
  '/result/case-c',
]) {
  test(`axe and demo banner on ${path}`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expectDemoBanner(page);
    await expectNoAxeViolations(page);
  });
}

test('keyboard: skip link moves focus to the main content', async ({ page }) => {
  await page.goto('/upload');
  await page.keyboard.press('Tab');
  const skip = page.getByRole('link', { name: strings.skipToContent });
  await expect(skip).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('main#main')).toBeFocused();
});

test('sample numbers are labelled wherever benchmark metrics appear', async ({ page }) => {
  await page.goto('/admin');
  const caption = page.locator('table caption');
  await expect(caption).toHaveText(new RegExp(`${strings.sourceSample}|${strings.sourceReport}`));
});
