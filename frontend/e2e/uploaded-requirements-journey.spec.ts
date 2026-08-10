import { test, expect } from '@playwright/test';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';

const here = dirname(fileURLToPath(import.meta.url));
const requirementScreenshot = resolve(
  here,
  '../../dump/ecommerce/New -screenies/55 - product specs ocr.png',
);

function pdfWithText(text: string): Buffer {
  const escaped = text.replaceAll('\\', '\\\\').replaceAll('(', '\\(').replaceAll(')', '\\)');
  const stream = `BT /F1 12 Tf 72 720 Td (${escaped}) Tj ET`;
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
    `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ];
  let body = '%PDF-1.4\n';
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(body));
    body += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xrefOffset = Buffer.byteLength(body);
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  body += offsets.slice(1).map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;
  return Buffer.from(body, 'binary');
}

test('requirements screenshot becomes reviewable provisional claims', async ({ page }) => {
  test.setTimeout(180_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}`;
  await page.addInitScript(
    (uid) => sessionStorage.setItem('uid', uid),
    `enterprise-e2e-upload-${suffix}`,
  );
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click({ force: true });

  const input = page.getByPlaceholder('Type your message...');
  await input.fill('I need a laptop for digital-twin simulation of factory equipment and predicting breakdowns.');
  await input.press('Enter');
  await expect(page.getByTestId('ambiguity-exploration')).toBeVisible({ timeout: 45_000 });

  await page.locator("input[type='file']").last().setInputFiles(requirementScreenshot);
  await input.fill('Can you read these specifications?');
  await input.press('Enter');

  const review = page.getByTestId('buyer-requirement-review');
  await expect(review).toBeVisible({ timeout: 90_000 });
  await expect(review).toContainText(/provisional and unverified/i);
  await expect(review.getByRole('textbox', { name: 'Correct ram gb value' }).first()).toHaveValue('32');
  await expect(review.getByRole('textbox', { name: 'Correct storage gb value' }).first()).toHaveValue('1000');
  await expect(review.getByRole('textbox', { name: 'Correct operating system value' })).toHaveValue('Windows 11 Pro');
  await expect(page.getByText(/image content looks unsafe/i)).toHaveCount(0);
  await expect(page.getByText(/provide an approved requirements document/i)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);

  await review.getByRole('textbox', { name: 'Correct ram gb value' }).first().fill('64');
  await review.getByRole('button', { name: 'Research and corroborate' }).click();
  const reconciliation = page.getByTestId('buyer-claim-reconciliation');
  await expect(reconciliation).toBeVisible({ timeout: 60_000 });
  await expect(reconciliation).toContainText(/corroborated|contradicted|unresolved|preference only/i);
  const shelves = page.getByTestId('product-shelves');
  await expect(shelves).toBeVisible({ timeout: 30_000 });
  await expect(shelves).toContainText(/official research|approved-source research|provisional/i);
  await expect(shelves).toContainText(/best across accepted shared needs/i);
  await expect(shelves).toContainText(/mobile workstation/i);
  await expect(shelves).toContainText(/freshness:\s*specification/i);
  await expect(page.getByText(/completed approved-source/i)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);
});

test('PDF requirements use the same review and correction contract', async ({ page }) => {
  test.setTimeout(180_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}`;
  await page.addInitScript(
    (uid) => sessionStorage.setItem('uid', uid),
    `enterprise-e2e-pdf-upload-${suffix}`,
  );
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click({ force: true });
  const input = page.getByPlaceholder('Type your message...');
  await input.fill('I need to simulate a PLC-controlled factory using Factory I/O.');
  await input.press('Enter');
  await expect(page.getByTestId('ambiguity-exploration')).toBeVisible({ timeout: 45_000 });
  await page.locator("input[type='file'][accept*='.pdf']").setInputFiles({
    name: 'buyer-requirements.pdf',
    mimeType: 'application/pdf',
    buffer: pdfWithText('RAM 32GB minimum Storage 1TB NVMe Windows 11 Pro recommended'),
  });
  await expect(page.getByTestId('attached-requirement-documents')).toContainText('buyer-requirements.pdf');
  await input.fill('Use this PDF for laptop recommendations.');
  await input.press('Enter');

  const review = page.getByTestId('buyer-requirement-review');
  await expect(review).toBeVisible({ timeout: 90_000 });
  await expect(review.getByRole('textbox', { name: 'Correct ram gb value' })).toHaveValue('32');
  await review.getByRole('textbox', { name: 'Correct ram gb value' }).fill('64');
  await expect(review.getByRole('textbox', { name: 'Correct ram gb value' })).toHaveValue('64');
  await expect(page.getByText(/document could not be decoded safely/i)).toHaveCount(0);

  const pdfResearchResponse = page.waitForResponse((response) =>
    /\/api\/v1\/shopping-cases\/[^/]+\/requirement-proposals\/[^/]+\/accept$/.test(
      new URL(response.url()).pathname,
    ),
  );
  await review.getByRole('button', { name: 'Research and corroborate' }).click();
  const pdfResearch = await pdfResearchResponse;
  expect(pdfResearch.ok()).toBe(true);
  const pdfResearchBody = await pdfResearch.json();
  const pdfCaseId = pdfResearch.url().match(/shopping-cases\/([^/]+)\/requirement-proposals/)?.[1];
  expect(pdfResearchBody.case_id).toBe(pdfCaseId);
  await expect(page.getByTestId('buyer-claim-reconciliation')).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId('product-shelves')).toContainText(/best across accepted shared needs/i);
});

test('plain-text requirements use the same provisional review contract', async ({ page }) => {
  test.setTimeout(180_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}`;
  await page.addInitScript(
    (uid) => sessionStorage.setItem('uid', uid),
    `enterprise-e2e-text-upload-${suffix}`,
  );
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click({ force: true });
  const input = page.getByPlaceholder('Type your message...');
  await input.fill('I need to simulate a PLC-controlled factory using Factory I/O.');
  await input.press('Enter');
  await expect(page.getByTestId('ambiguity-exploration')).toBeVisible({ timeout: 45_000 });

  await page.locator("input[type='file'][accept*='.pdf']").setInputFiles({
    name: 'buyer-requirements.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from(
      'RAM 32GB minimum\nStorage 1TB NVMe\nWindows 11 Pro recommended',
      'utf-8',
    ),
  });
  await expect(page.getByTestId('attached-requirement-documents')).toContainText('buyer-requirements.txt');
  await input.fill('Use these requirements for laptop recommendations.');
  await input.press('Enter');

  const review = page.getByTestId('buyer-requirement-review');
  await expect(review).toBeVisible({ timeout: 90_000 });
  await expect(review.getByRole('textbox', { name: 'Correct ram gb value' })).toHaveValue('32');
  await expect(review.getByRole('textbox', { name: 'Correct storage gb value' })).toHaveValue('1000');
  await expect(review.getByRole('textbox', { name: 'Correct operating system value' })).toHaveValue('Windows 11 Pro');
  await expect(page.getByText(/homoglyph|unicode obfuscation/i)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);

  await review.getByRole('textbox', { name: 'Correct storage gb value' }).fill('2000');
  const textResearchResponse = page.waitForResponse((response) =>
    /\/api\/v1\/shopping-cases\/[^/]+\/requirement-proposals\/[^/]+\/accept$/.test(
      new URL(response.url()).pathname,
    ),
  );
  await review.getByRole('button', { name: 'Research and corroborate' }).click();
  const textResearch = await textResearchResponse;
  expect(textResearch.ok()).toBe(true);
  const textResearchBody = await textResearch.json();
  const textCaseId = textResearch.url().match(/shopping-cases\/([^/]+)\/requirement-proposals/)?.[1];
  expect(textResearchBody.case_id).toBe(textCaseId);
  await expect(page.getByTestId('buyer-claim-reconciliation')).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId('product-shelves')).toContainText(/best across accepted shared needs/i);
});
