// what an administrator may do with each person and why a control is off when it is. The API refuses an admin acting on their own
// account (403) and anything that would leave no active admin (409). The page does not wait to be refused: it switches those controls
// off and says why in words and it still handles the refusal if the API says it anyway (another admin may have acted a moment before).

export interface Person {
  id: string;
  name: string | null;
  email: string;
  role: 'admin' | 'technician' | 'viewer';
  created_at?: string;
  oauth_provider?: string | null;
  totp_enabled?: boolean;
  is_active?: boolean;
  last_login?: string | null;
  session_count?: number;
  // an account owned by an integration and not by a person. It cannot sign in and owns API tokens.
  is_service?: boolean;
}

export type PersonAction = 'role' | 'deactivate' | 'reactivate' | 'clear-two-step' | 'reset-link' | 'remove';

export interface ActionState {
  action: PersonAction;
  // false when the control is off, with the reason in words
  enabled: boolean;
  reason: string | null;
}

// an account is active unless the API says otherwise (an API that predates the field has no deactivated accounts)
export const isActive = (p: Person): boolean => p.is_active !== false;

export function activeAdminCount(people: readonly Person[]): number {
  return people.filter((p) => p.role === 'admin' && isActive(p)).length;
}

const SELF = 'You cannot do this to your own account. Ask another admin.';
const LAST = 'This is the only active admin. Make another person an admin first.';

export function actionsFor(person: Person, meId: string | null | undefined, people: readonly Person[]): ActionState[] {
  const self = Boolean(meId) && person.id === meId;
  const lastAdmin = person.role === 'admin' && isActive(person) && activeAdminCount(people) <= 1;
  const off = (action: PersonAction, reason: string): ActionState => ({ action, enabled: false, reason });
  const on = (action: PersonAction): ActionState => ({ action, enabled: true, reason: null });

  const out: ActionState[] = [];
  out.push(self ? off('role', SELF) : lastAdmin ? off('role', LAST) : on('role'));
  if (isActive(person)) out.push(self ? off('deactivate', SELF) : lastAdmin ? off('deactivate', LAST) : on('deactivate'));
  else out.push(on('reactivate'));
  out.push(person.totp_enabled ? on('clear-two-step') : off('clear-two-step', 'Two-step sign-in is not on for this person.'));
  out.push(isActive(person) ? on('reset-link') : off('reset-link', 'A deactivated account cannot be sent a reset link. Reactivate it first.'));
  out.push(self ? off('remove', SELF) : lastAdmin ? off('remove', LAST) : on('remove'));
  return out;
}

export const ACTION_LABELS: Readonly<Record<PersonAction, string>> = {
  role: 'Change role',
  deactivate: 'Deactivate',
  reactivate: 'Reactivate',
  'clear-two-step': 'Clear two-step',
  'reset-link': 'Send reset link',
  remove: 'Remove',
};

export const isService = (p: Person): boolean => p.is_service === true;

// a service account has a role and owns API tokens and nothing else: no sign-in, no two-step, no reset link. An admin may change its
// role, deactivate and reactivate it and remove it through the same /users routes as a person. The same last-active-admin rule applies.
export function serviceActionsFor(account: Person, people: readonly Person[]): ActionState[] {
  const lastAdmin = account.role === 'admin' && isActive(account) && activeAdminCount(people) <= 1;
  const off = (action: PersonAction, reason: string): ActionState => ({ action, enabled: false, reason });
  const on = (action: PersonAction): ActionState => ({ action, enabled: true, reason: null });
  return [
    lastAdmin ? off('role', LAST) : on('role'),
    isActive(account) ? (lastAdmin ? off('deactivate', LAST) : on('deactivate')) : on('reactivate'),
    lastAdmin ? off('remove', LAST) : on('remove'),
  ];
}
