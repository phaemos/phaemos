// one small store for the analytics choice, shared by the banner, the settings
// button and the analytics tag. It works through useSyncExternalStore:
// subscribe, getSnapshot and getServerSnapshot are the three functions it needs.

export const CONSENT_KEY = 'cookie_consent';

export type ConsentChoice = 'accepted' | 'declined';
// unset: no choice yet. unknown: server rendering, where storage cannot be read.
export type ConsentState = ConsentChoice | 'unset' | 'unknown';

const listeners = new Set<() => void>();

// a copy of the choice for visits where storage cannot be used (some private
// windows throw). It is only consulted when storage fails, so a choice removed
// from storage in another tab is never hidden by a stale copy.
let memoryChoice: ConsentChoice | null = null;
let promptOpen = false;
let storageListening = false;

function notify() {
  listeners.forEach((listener) => listener());
}

function isChoice(value: unknown): value is ConsentChoice {
  return value === 'accepted' || value === 'declined';
}

export function readConsent(): ConsentState {
  if (typeof window === 'undefined') return 'unknown';
  try {
    const value = window.localStorage.getItem(CONSENT_KEY);
    return isChoice(value) ? value : 'unset';
  } catch {
    return memoryChoice ?? 'unset';
  }
}

export function writeConsent(choice: ConsentChoice): void {
  try {
    window.localStorage.setItem(CONSENT_KEY, choice);
    memoryChoice = null;
  } catch {
    // storage is unusable here, so the in-memory copy carries the choice for this visit
    memoryChoice = choice;
  }
  notify();
}

function onStorage(event: StorageEvent) {
  // key is null when storage was cleared in another tab
  if (event.key === null || event.key === CONSENT_KEY) notify();
}

// the storage event only fires in the other tabs, so same-tab changes go
// through the listener set above and cross-tab changes through this event.
export function subscribeConsent(listener: () => void): () => void {
  listeners.add(listener);
  if (!storageListening && typeof window !== 'undefined') {
    window.addEventListener('storage', onStorage);
    storageListening = true;
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && storageListening) {
      window.removeEventListener('storage', onStorage);
      storageListening = false;
    }
  };
}

export function getServerConsent(): ConsentState {
  return 'unknown';
}

// the banner can be reopened after a choice, so withdrawing is as easy as giving.
export function openConsentPrompt(): void {
  promptOpen = true;
  notify();
}

export function closeConsentPrompt(): void {
  promptOpen = false;
  notify();
}

export function getPromptOpen(): boolean {
  return promptOpen;
}

export function getServerPromptOpen(): boolean {
  return false;
}

// google's documented switch: while it is true the tag sends nothing for that id.
export function setAnalyticsDisabled(id: string, disabled: boolean): void {
  (window as unknown as Record<string, unknown>)[`ga-disable-${id}`] = disabled;
}

export function isAnalyticsCookie(name: string): boolean {
  return name === '_ga' || name.startsWith('_ga_');
}

// the tag sets its cookies on the widest domain it is allowed to, so expiry is tried
// on the host and on every parent domain below the public suffix.
export function clearAnalyticsCookies(): void {
  if (typeof document === 'undefined') return;
  const names = document.cookie
    .split(';')
    .map((part) => part.split('=')[0].trim())
    .filter(isAnalyticsCookie);
  if (names.length === 0) return;

  const parts = window.location.hostname.split('.');
  const domains: (string | null)[] = [null];
  for (let i = 0; i < parts.length - 1; i += 1) {
    domains.push(parts.slice(i).join('.'));
  }
  for (const name of names) {
    for (const domain of domains) {
      const scope = domain ? `; domain=${domain}` : '';
      document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/${scope}`;
    }
  }
}

// test helper: forget in-memory state so each test starts clean
export function resetConsentForTests(): void {
  memoryChoice = null;
  promptOpen = false;
  listeners.clear();
  if (storageListening && typeof window !== 'undefined') {
    window.removeEventListener('storage', onStorage);
  }
  storageListening = false;
}
