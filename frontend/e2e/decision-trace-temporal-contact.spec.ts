import { expect, test } from '@playwright/test';


async function openScenario(page: any, schedule: any, humanRoom?: any) {
  await page.addInitScript(() => window.sessionStorage.setItem('ss_owner_key', 'operator-test-key'));
  await page.route('**/api/v1/decisions/trace-temporal/**', (route: any) => route.fulfill({ json: {} }));
  await page.route('**/api/v1/decisions/trace-temporal', (route: any) => route.fulfill({ json: {
    trace_id: 'trace-temporal', events: [{ id: 'e1', seq: 1, event_type: 'procurement_case_opened',
      source_id: 'Procurement_Agent', timestamp: '2026-08-08T01:00:00Z', payload: {} }],
  } }));
  await page.route('**/api/v1/fulfillment/cases/by-trace/trace-temporal/all/operator-view',
    (route: any) => route.fulfill({ json: { cases: [{ case_id: 'case-temporal', state: 'AWAITING_APPROVAL',
      state_json: { availability: { item_ref: 'SKU-TIME' } } }] } }));
  await page.route('**/api/v1/fulfillment/cases/case-temporal/journey',
    (route: any) => route.fulfill({ json: { journey: [] } }));
  await page.route('**/api/v1/admin/allocation/workbench?sku=SKU-TIME',
    (route: any) => route.fulfill({ json: {
      summary: { committed_quantity: 20, allocated_quantity: 10, shortfall_quantity: 10,
        allocation_pressure: 0.5, oldest_queue_age_seconds: 120 },
      outbound_contact_schedule: schedule, human_room: humanRoom,
    } }));
  await page.goto('/?trace=trace-temporal&tracetab=procurement');
  return page.getByRole('dialog', { name: /Decision Trace/i });
}


test('weekend email transmits while supplier response SLA remains paused', async ({ page }) => {
  const trace = await openScenario(page, {
    channel: 'email', queue_state: 'pending', transport_eligible: true,
    not_before: '2026-08-08T01:00:00+00:00', sla_clock: 'paused',
    schedule_reason: 'email_transmits_sla_paused',
  });
  const schedule = trace.getByTestId('proc-contact-schedule');
  await expect(schedule).toContainText('email');
  await expect(schedule).toContainText('SLA clockpaused');
  await expect(schedule).toContainText('Transporteligible now');
});


test('phone-only supplier stays queued and opens a procurement human room', async ({ page }) => {
  const trace = await openScenario(page, {
    channel: 'phone', queue_state: 'queued_contact', transport_eligible: false,
    not_before: '2026-08-10T23:00:00+00:00', sla_clock: 'paused',
    schedule_reason: 'human_phone_contact_required',
  }, { state: 'requested', assigned_operator_id: null, version: 1 });
  await expect(trace.getByTestId('proc-contact-schedule')).toContainText('not executable by email worker');
  await expect(trace.getByTestId('proc-human-room')).toContainText('Room staterequested');
});
