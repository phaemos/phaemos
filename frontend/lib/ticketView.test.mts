// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { assigneeLabel, assigneeOptions, buildTicketPatch, DEFAULT_TICKET_FILTERS, draftFromTicket, filterTickets, formatTicketNumber, parseTicketFilters, ticketFiltersToQuery } from './ticketView.ts';

const ID = '33333333-3333-4333-8333-333333333333';
const ME = '44444444-4444-4444-8444-444444444444';
const OTHER = '55555555-5555-4555-8555-555555555555';

test('an empty query gives the defaults', () => {
  assert.deepEqual(parseTicketFilters(new URLSearchParams('')), DEFAULT_TICKET_FILTERS);
});

test('reads status, priority and the open ticket', () => {
  const f = parseTicketFilters(new URLSearchParams(`status=in_progress&priority=high&ticket=${ID}`));
  assert.deepEqual(f, { status: 'in_progress', priority: 'high', ticket: ID });
  assert.deepEqual(parseTicketFilters(new URLSearchParams(ticketFiltersToQuery(f))), f);
});

test('unknown values fall back', () => {
  const f = parseTicketFilters(new URLSearchParams('status=done&priority=urgent&ticket=../../x'));
  assert.deepEqual(f, DEFAULT_TICKET_FILTERS);
  assert.equal(ticketFiltersToQuery(DEFAULT_TICKET_FILTERS), '');
});

test('filters tickets', () => {
  const list = [
    { status: 'open' as const, priority: 'high' as const },
    { status: 'closed' as const, priority: 'high' as const },
    { status: 'open' as const, priority: null },
  ];
  assert.equal(filterTickets(list, { ...DEFAULT_TICKET_FILTERS, status: 'open' }).length, 2);
  assert.equal(filterTickets(list, { ...DEFAULT_TICKET_FILTERS, priority: 'high' }).length, 2);
  assert.equal(filterTickets(list, { ...DEFAULT_TICKET_FILTERS, status: 'open', priority: 'high' }).length, 1);
});

test('ticket numbers are padded and a missing one says so', () => {
  assert.equal(formatTicketNumber(7), 'PHM-0007');
  assert.equal(formatTicketNumber(12345), 'PHM-12345');
  assert.equal(formatTicketNumber(null), 'No number');
});

test('assignee words depend on what the viewer may know', () => {
  const people = [{ id: OTHER, name: 'Sam Jones', email: 'sam@example.com' }, { id: ME, name: null, email: 'me@example.com' }];
  assert.equal(assigneeLabel(null, { meId: ME, people: null }), 'Unassigned');
  assert.equal(assigneeLabel(ME, { meId: ME, people: null }), 'You');
  assert.equal(assigneeLabel(OTHER, { meId: ME, people: null }), 'Assigned');
  assert.equal(assigneeLabel(OTHER, { meId: ME, people }), 'Sam Jones');
  assert.equal(assigneeLabel(ID, { meId: ME, people }), 'Assigned');
});

test('the patch holds only changed fields and never an empty value', () => {
  const t = { status: 'open' as const, priority: null, assigned_to: null };
  assert.deepEqual(buildTicketPatch(t, draftFromTicket(t)), {});
  assert.deepEqual(buildTicketPatch(t, { status: 'closed', priority: 'high', assigned_to: ME }), { status: 'closed', priority: 'high', assigned_to: ME });
  const assigned = { status: 'in_progress' as const, priority: 'low' as const, assigned_to: ME };
  assert.deepEqual(buildTicketPatch(assigned, { status: 'in_progress', priority: '', assigned_to: '' }), {});
  assert.deepEqual(buildTicketPatch(assigned, { status: 'in_progress', priority: 'low', assigned_to: OTHER }), { assigned_to: OTHER });
});

test('an admin can pick anyone and a ticket with an assignee has no Unassigned option', () => {
  const people = [{ id: OTHER, name: 'Sam Jones', email: 's@example.com', role: 'technician' }, { id: ME, name: null, email: 'me@example.com', role: 'admin' }];
  const free = assigneeOptions(null, { meId: ME, people });
  assert.deepEqual(free.map((o) => o.label), ['Unassigned', 'Sam Jones (Technician)', 'me@example.com (Admin)']);
  const taken = assigneeOptions(OTHER, { meId: ME, people });
  assert.equal(taken.some((o) => o.value === ''), false);
  // an assignee the list does not hold is kept so the select stays valid
  const unknown = assigneeOptions(ID, { meId: ME, people });
  assert.deepEqual(unknown.at(-1), { value: ID, label: 'Assigned' });
});

test('another role can only keep the assignee or take the ticket', () => {
  assert.deepEqual(assigneeOptions(null, { meId: ME, people: null }), [{ value: '', label: 'Unassigned' }, { value: ME, label: 'Assign to me' }]);
  assert.deepEqual(assigneeOptions(OTHER, { meId: ME, people: null }), [{ value: OTHER, label: 'Assigned' }, { value: ME, label: 'Assign to me' }]);
  assert.deepEqual(assigneeOptions(ME, { meId: ME, people: null }), [{ value: ME, label: 'You' }]);
  assert.deepEqual(assigneeOptions(null, { meId: null, people: null }), [{ value: '', label: 'Unassigned' }]);
});
