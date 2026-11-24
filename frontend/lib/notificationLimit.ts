// the daily limit on alert emails and texts. The API does not put this on any alert or metrics route: when a channel's limit stops
// messages it writes one audit entry for the UTC day (`alert_cap_reached`, its resource the channel) and says "paused until 00:00
// UTC". Only an admin can read the audit log, so only an admin's page can show the notice. Alerts themselves are always recorded;
// no import, so the tests can load it.

export interface AuditEntryLike {
  action?: string | null;
  resource?: string | null;
  detail?: string | null;
  created_at?: string | null;
}

export interface LimitReached {
  // "email" or "text message"
  channel: string;
  // the cap that was reached, when the entry says
  cap: number | null;
  // when messages start again: the next 00:00 UTC after the entry
  resumesAt: string;
}

const CHANNEL_WORDS: Record<string, string> = { email: 'email', sms: 'text message' };

// the start of the next UTC day after a moment, as an ISO string
export function nextUtcMidnight(from: number): string {
  const d = new Date(from);
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 1)).toISOString();
}

// the limits reached today (UTC) that are still in force at `now`. Yesterday's entry says "until 00:00 UTC", which has passed.
export function limitsReached(entries: readonly AuditEntryLike[] | null | undefined, now: number): LimitReached[] {
  const out = new Map<string, LimitReached>();
  for (const e of entries ?? []) {
    if (e.action !== 'alert_cap_reached' || !e.created_at) continue;
    const at = Date.parse(e.created_at);
    if (Number.isNaN(at)) continue;
    const resumes = nextUtcMidnight(at);
    if (Date.parse(resumes) <= now) continue;
    const channel = Object.hasOwn(CHANNEL_WORDS, e.resource ?? '') ? CHANNEL_WORDS[e.resource as string] : (e.resource ?? 'message').slice(0, 20);
    const cap = /limit of (\d+)/.exec(e.detail ?? '')?.[1];
    if (!out.has(channel)) out.set(channel, { channel, cap: cap ? Number(cap) : null, resumesAt: resumes });
  }
  return [...out.values()];
}

// "Alerts are still recorded here, but email and text messages stopped ...". Times are written by the caller, so this takes the words.
export function limitSentence(limits: readonly LimitReached[], when: string): string {
  const channels = limits.map((l) => l.channel);
  const list = channels.length > 1 ? `${channels.slice(0, -1).join(', ')} and ${channels[channels.length - 1]}` : channels[0] ?? 'message';
  const word = channels.length > 1 ? 'limits' : 'limit';
  return `The daily ${list} ${word} was reached. Alerts are still recorded and shown here, but ${list} messages have stopped until ${when}.`;
}

// "00:00 UTC on 23 Nov 2026": the limit resets at midnight UTC, which is not midnight for the reader, so the zone is named
export function resumeWords(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '00:00 UTC';
  return `00:00 UTC on ${d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })}`;
}

export interface DailyLimit {
  limit?: number;
  count?: number;
  reached?: boolean;
  resets_at?: string;
}

// the limits reached now, from `daily_limits` on GET /alert-metrics (every signed-in role can read it)
export function limitsFromMetrics(daily: Record<string, DailyLimit> | null | undefined): LimitReached[] {
  const out: LimitReached[] = [];
  for (const [key, d] of Object.entries(daily ?? {})) {
    if (!d || d.reached !== true) continue;
    const channel = Object.hasOwn(CHANNEL_WORDS, key) ? CHANNEL_WORDS[key] : key.slice(0, 20);
    out.push({ channel, cap: typeof d.limit === 'number' ? d.limit : null, resumesAt: typeof d.resets_at === 'string' && !Number.isNaN(Date.parse(d.resets_at)) ? d.resets_at : nextUtcMidnight(Date.now()) });
  }
  return out;
}
