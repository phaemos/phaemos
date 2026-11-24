// pure logic for the tickets page: the filters kept in the address, the ticket number, who a ticket is assigned to
// and the body of an update. The API accepts a change to status, priority and assignee but it ignores a null, so a
// field can be changed and never cleared. buildTicketPatch relies on that.
import type { Ticket } from '@/types';

export type TicketStatusKey = 'open' | 'in_progress' | 'closed';
export type TicketPriorityKey = 'critical' | 'high' | 'medium' | 'low';

export interface TicketFilters {
  status: 'all' | TicketStatusKey;
  priority: 'all' | TicketPriorityKey;
  // the ticket open in the detail panel. An empty string means none
  ticket: string;
}

export const DEFAULT_TICKET_FILTERS: TicketFilters = { status: 'all', priority: 'all', ticket: '' };

interface ParamSource {
  get(name: string): string | null;
}

const ID = /^[0-9a-f-]{32,40}$/i;

export function parseTicketFilters(params: ParamSource): TicketFilters {
  const status = params.get('status');
  const priority = params.get('priority');
  const ticket = params.get('ticket')?.trim() ?? '';
  return {
    status: status === 'open' || status === 'in_progress' || status === 'closed' ? status : 'all',
    priority: priority === 'critical' || priority === 'high' || priority === 'medium' || priority === 'low' ? priority : 'all',
    ticket: ID.test(ticket) ? ticket : '',
  };
}

export function ticketFiltersToQuery(filters: TicketFilters): string {
  const q = new URLSearchParams();
  if (filters.status !== 'all') q.set('status', filters.status);
  if (filters.priority !== 'all') q.set('priority', filters.priority);
  if (filters.ticket) q.set('ticket', filters.ticket);
  return q.toString();
}

export function filterTickets<T extends Pick<Ticket, 'status' | 'priority'>>(tickets: readonly T[], filters: TicketFilters): T[] {
  return tickets.filter((t) => {
    if (filters.status !== 'all' && t.status !== filters.status) return false;
    if (filters.priority !== 'all' && t.priority !== filters.priority) return false;
    return true;
  });
}

export function formatTicketNumber(n: number | null | undefined): string {
  if (n === null || n === undefined) return 'No number';
  return `PHM-${n.toString().padStart(4, '0')}`;
}

export interface Person {
  id: string;
  name: string | null;
  email: string;
  role?: string;
}

export interface AssigneeContext {
  // the signed-in user, when known
  meId: string | null;
  // everyone, which only an admin can list. Null for other roles.
  people: readonly Person[] | null;
}

export function personName(p: Person): string {
  return p.name?.trim() || p.email;
}

// the truest words for an assignee. A name when we can know it, "You" for the signed-in user and otherwise
// "Assigned", because only admins can look up another user.
export function assigneeLabel(assignedTo: string | null, ctx: AssigneeContext): string {
  if (!assignedTo) return 'Unassigned';
  if (ctx.meId && assignedTo === ctx.meId) return 'You';
  const person = ctx.people?.find((p) => p.id === assignedTo);
  return person ? personName(person) : 'Assigned';
}

export interface TicketDraft {
  status: TicketStatusKey;
  priority: TicketPriorityKey | '';
  assigned_to: string;
}

export function draftFromTicket(t: Pick<Ticket, 'status' | 'priority' | 'assigned_to'>): TicketDraft {
  return { status: t.status, priority: t.priority ?? '', assigned_to: t.assigned_to ?? '' };
}

// only the fields that changed. An empty draft value is never sent because the API would ignore a null.
export function buildTicketPatch(original: Pick<Ticket, 'status' | 'priority' | 'assigned_to'>, draft: TicketDraft): Partial<Pick<Ticket, 'status' | 'priority' | 'assigned_to'>> {
  const patch: Partial<Pick<Ticket, 'status' | 'priority' | 'assigned_to'>> = {};
  if (draft.status !== original.status) patch.status = draft.status;
  if (draft.priority && draft.priority !== original.priority) patch.priority = draft.priority;
  if (draft.assigned_to && draft.assigned_to !== original.assigned_to) patch.assigned_to = draft.assigned_to;
  return patch;
}

export function newestFirst<T extends { created_at: string }>(tickets: readonly T[]): T[] {
  const t = (iso: string) => {
    const n = Date.parse(iso);
    return Number.isNaN(n) ? 0 : n;
  };
  return [...tickets].sort((a, b) => t(b.created_at) - t(a.created_at));
}

export interface AssigneeOption {
  value: string;
  label: string;
}

// what the assignee select offers. An admin can list users and so can pick anyone. Every other role can only keep the
// current assignee or take the ticket, because their account cannot look up another person. The current assignee is
// always present so the select never shows a value that is not an option. "Unassigned" is offered only while the
// ticket has no assignee, since the API cannot clear one.
export function assigneeOptions(assignedTo: string | null, ctx: AssigneeContext): AssigneeOption[] {
  const out: AssigneeOption[] = [];
  if (!assignedTo) out.push({ value: '', label: 'Unassigned' });
  if (ctx.people) {
    for (const p of ctx.people) out.push({ value: p.id, label: p.role ? `${personName(p)} (${p.role.charAt(0).toUpperCase()}${p.role.slice(1)})` : personName(p) });
    if (assignedTo && !ctx.people.some((p) => p.id === assignedTo)) {
      out.push({ value: assignedTo, label: assigneeLabel(assignedTo, ctx) });
    }
    return out;
  }
  if (assignedTo) out.push({ value: assignedTo, label: assigneeLabel(assignedTo, ctx) });
  if (ctx.meId && assignedTo !== ctx.meId) out.push({ value: ctx.meId, label: 'Assign to me' });
  return out;
}
