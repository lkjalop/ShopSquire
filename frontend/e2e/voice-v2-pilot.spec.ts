import { expect, test } from '@playwright/test';

const UID = `e2e-voice-v2-${Date.now()}`;
const SPOKEN_QUERY = 'gaming laptop under 2000';

test('spoken and typed input share the canonical V2 recommendation path', async ({ context, page }) => {
  test.setTimeout(180_000);
  await context.grantPermissions(['microphone'], { origin: 'http://localhost:5173' });
  await page.addInitScript(({ uid, transcript }) => {
    sessionStorage.setItem('uid', uid);

    class FakeSpeechRecognition {
      continuous = false;
      interimResults = true;
      lang = '';
      onresult: ((event: unknown) => void) | null = null;
      onerror: ((event: unknown) => void) | null = null;
      onend: (() => void) | null = null;

      start() {
        window.setTimeout(() => {
          const result = Object.assign(
            [{ transcript }],
            { isFinal: true },
          );
          this.onresult?.({ results: [result] });
          this.onend?.();
        }, 20);
      }

      stop() {
        this.onend?.();
      }
    }

    class FakeMediaRecorder {
      static isTypeSupported() {
        return true;
      }

      state = 'inactive';
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;

      constructor(_stream: MediaStream, _options?: MediaRecorderOptions) {}

      start() {
        this.state = 'recording';
      }

      stop() {
        this.state = 'inactive';
        this.onstop?.();
      }
    }

    Object.defineProperty(window, 'webkitSpeechRecognition', {
      configurable: true,
      value: FakeSpeechRecognition,
    });
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: FakeMediaRecorder,
    });
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: async () => ({
          getTracks: () => [{ stop: () => undefined }],
        }),
      },
    });
  }, { uid: UID, transcript: SPOKEN_QUERY });

  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();
  const mic = page.getByTitle('Voice input');
  await expect(mic).toBeVisible();
  await mic.click();

  const input = page.locator('textarea').last();
  await expect(input).toHaveValue(SPOKEN_QUERY);
  await page.getByTitle('Click to stop recording').click();
  await input.press('Enter');

  await expect(page.getByText(SPOKEN_QUERY, { exact: false })).toBeVisible();
  await expect(page.getByTitle('Sent via voice')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add', exact: true }).first())
    .toBeVisible({ timeout: 90_000 });

  await page.getByTitle('Decision Trace').click();
  const trace = page.getByTestId('decision-trace-modal');
  await expect(trace).toBeVisible();

  await trace.getByRole('button', { name: 'Execution', exact: true }).click();
  await expect(trace.getByText('Who decided what')).toBeVisible();
  await expect(trace.getByText(/Models propose\. Platform gates authorize/i)).toBeVisible();
  await expect(trace.getByText('Proposes', { exact: true })).toBeVisible();
  await expect(trace.getByText('Authorizes', { exact: true }).first()).toBeVisible();

  await trace.getByRole('button', { name: 'Events', exact: true }).click();
  await expect(trace.getByText(/Candidate Retrieval|Trace Persistence/i).first()).toBeVisible();
  await expect(trace.getByText(/Candidate_Retrieval_Agent/)).toHaveCount(0);

  await trace.getByRole('button', { name: 'Summary', exact: true }).click();
  await expect(trace.getByText(/V2 served/i)).toBeVisible();
  await expect(trace.getByText(/Canonical slate/i)).toBeVisible();
  await expect(trace.getByText(/Verified/i)).toBeVisible();

  await trace.getByRole('button', { name: 'Why Recommended', exact: true }).click();
  await expect(trace.getByText('All Ranked Products')).toBeVisible();
  const whySku = (await trace.locator('text=/R?GAM-[A-Z0-9]+/').first().innerText()).trim();
  expect(whySku).toMatch(/^R?GAM-[A-Z0-9]+$/);

  await trace.getByRole('button', { name: 'Intent', exact: true }).click();
  await expect(trace.getByText(/Shopper Intent Profile|Lane/i).first()).toBeVisible();

  await trace.getByRole('button', { name: 'Multimodal', exact: true }).click();
  await expect(trace.getByText('Voice Used', { exact: true })).toBeVisible();
  await expect(trace.getByText('Yes', { exact: true }).first()).toBeVisible();

  await trace.getByRole('button', { name: 'Complexity', exact: true }).click();
  await expect(trace.getByText('Complexity Score')).toBeVisible();

  await trace.getByRole('button', { name: 'Memory', exact: true }).click();
  await expect(trace.getByText(/No memory\/cache events|Memory/i).first()).toBeVisible();

  await trace.getByRole('button', { name: 'Security Matrix', exact: true }).click();
  await expect(trace.getByText(/Text-only turn.*no image uploaded/i)).toBeVisible();

  await trace.getByRole('button', { name: /Procurement/ }).click();
  await expect(trace.getByText(/No procurement .* activity/i)).toBeVisible();

  await trace.getByRole('button', { name: 'Audit Trail', exact: true }).click();
  await expect(trace.getByText('Bitemporal Decision Audit')).toBeVisible();
  await expect(trace.getByText('Recommendation_Core')).toBeVisible();

  await trace.getByRole('button', { name: 'Raw', exact: true }).click();
  await expect(trace.getByText(/canonical_identity/)).toBeVisible();
  await expect(trace.getByText(new RegExp(whySku))).toBeVisible();
});
