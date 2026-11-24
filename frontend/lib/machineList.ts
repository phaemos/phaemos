// filtering, sorting and wording for the machines list. The API returns machines newest first and takes no sort
// parameter, so the page loads the fleet in one request and orders it here.

export interface MachineLike {
  id: string;
  name: string;
  location: string | null;
  type: string | null;
  status: string;
  last_seen: string | null;
  tags: string[] | null;
}

export type SortKey = 'attention' | 'name' | 'recent' | 'location';

export const SORT_OPTIONS: readonly { value: SortKey; label: string }[] = [
  { value: 'attention', label: 'Needs attention first' },
  { value: 'name', label: 'Name' },
  { value: 'recent', label: 'Last seen, newest first' },
  { value: 'location', label: 'Location' },
];

// worst first, so a machine in fault is never below the fold. An unknown status sorts after the known ones
const RANK: Record<string, number> = { fault: 0, warning: 1, offline: 2, online: 3 };

const byName = (a: MachineLike, b: MachineLike) => a.name.localeCompare(b.name, 'en-GB', { numeric: true, sensitivity: 'base' });
const time = (m: MachineLike) => (m.last_seen ? new Date(m.last_seen).getTime() || 0 : 0);

// `rank` orders the "needs attention" sort, worst first. The page passes one built from each machine's state, because the
// API's own status only says online or offline. Without it the older status field decides.
export function sortMachines<T extends MachineLike>(list: readonly T[], key: SortKey, rank?: (m: T) => number): T[] {
  const out = [...list];
  switch (key) {
    case 'name':
      return out.sort(byName);
    case 'recent':
      // a machine that has never reported goes last
      return out.sort((a, b) => time(b) - time(a) || byName(a, b));
    case 'location':
      // no location goes last
      return out.sort((a, b) => {
        if (!a.location && !b.location) return byName(a, b);
        if (!a.location) return 1;
        if (!b.location) return -1;
        return a.location.localeCompare(b.location, 'en-GB', { numeric: true, sensitivity: 'base' }) || byName(a, b);
      });
    default:
      return out.sort((a, b) => (rank ? rank(a) - rank(b) : (RANK[a.status] ?? 4) - (RANK[b.status] ?? 4)) || byName(a, b));
  }
}

export interface MachineFilter {
  // '' means any
  status: string;
  tag: string;
  search: string;
}

export function filterMachines<T extends MachineLike>(list: readonly T[], f: MachineFilter): T[] {
  const q = f.search.trim().toLowerCase();
  return list.filter((m) => {
    if (f.status && m.status !== f.status) return false;
    if (f.tag && !(m.tags ?? []).includes(f.tag)) return false;
    if (q && !m.name.toLowerCase().includes(q)) return false;
    return true;
  });
}

// every tag in use, sorted, with how many machines carry it
export function tagCounts(list: readonly MachineLike[]): { tag: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const m of list) for (const t of new Set(m.tags ?? [])) counts.set(t, (counts.get(t) ?? 0) + 1);
  return [...counts.entries()].map(([tag, count]) => ({ tag, count })).sort((a, b) => a.tag.localeCompare(b.tag, 'en-GB'));
}

// "Showing 3 of 12 machines" while a filter hides some and "12 machines" when nothing is hidden
export function countLine(shown: number, total: number): string {
  const noun = (n: number) => (n === 1 ? 'machine' : 'machines');
  return shown === total ? `${total} ${noun(total)}` : `Showing ${shown} of ${total} ${noun(total)}`;
}

// "1 machine" or "3 machines", for the firmware confirmation
export function machineCount(n: number): string {
  return `${n} ${n === 1 ? 'machine' : 'machines'}`;
}

export interface OwnerContext {
  // id to name for the people the signed-in role may list. Empty for a role that may not list people
  names: Record<string, string>;
  // the signed-in user's own id and name, from /auth/me
  me?: { id: string; name: string | null; email: string } | null;
}

// the owner as the signed-in role can describe it. The API returns only an owner id and lists people to admins
// alone, so a technician or viewer can name themselves and nobody else. Never claims "Unassigned" for a machine
// that has an owner.
export function ownerLabel(ownerId: string | null, ctx: OwnerContext): string {
  if (!ownerId) return 'Unassigned';
  if (ctx.names[ownerId]) return ctx.names[ownerId];
  if (ctx.me && ctx.me.id === ownerId) return `${ctx.me.name ?? ctx.me.email} (you)`;
  return 'Another technician';
}

// the view of the machines list: its search, filters and sort order live in the address, as they do on the alerts and
// tickets pages, so a view can be linked and survives a reload.
export interface MachineView {
  search: string;
  // what the machine is: healthy, warning, fault or unknown. '' means any
  state: string;
  // how it is watched: online, late or offline. '' means any
  link: string;
  tag: string;
  sort: SortKey;
}

export const DEFAULT_MACHINE_VIEW: MachineView = { search: '', state: '', link: '', tag: '', sort: 'attention' };

const STATES = ['healthy', 'warning', 'fault', 'unknown'];
const LINKS = ['online', 'late', 'offline'];

interface ParamSource {
  get(name: string): string | null;
}

// an unknown or missing value falls back to the default, so a hand-edited link never breaks the page
export function parseMachineView(params: ParamSource): MachineView {
  const sort = params.get('sort');
  const state = params.get('state') ?? '';
  const link = params.get('link') ?? '';
  return {
    search: (params.get('q') ?? '').slice(0, 80),
    state: STATES.includes(state) ? state : '',
    link: LINKS.includes(link) ? link : '',
    tag: (params.get('tag') ?? '').trim().slice(0, 60),
    sort: SORT_OPTIONS.some((o) => o.value === sort) ? (sort as SortKey) : DEFAULT_MACHINE_VIEW.sort,
  };
}

// only the values that differ from the defaults are written, so the plain page keeps a plain address
export function machineViewToQuery(view: MachineView): string {
  const q = new URLSearchParams();
  if (view.search.trim()) q.set('q', view.search);
  if (view.state) q.set('state', view.state);
  if (view.link) q.set('link', view.link);
  if (view.tag) q.set('tag', view.tag);
  if (view.sort !== DEFAULT_MACHINE_VIEW.sort) q.set('sort', view.sort);
  return q.toString();
}
