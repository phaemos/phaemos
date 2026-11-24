// replay protection in the machine's health panel. The API writes the sentences itself (`replay_status`, `replay_warning`,
// `replay_recovery`), so they are shown as they come and nothing here rewrites them. This only decides what to show and whether the
// admin's action applies. No import, so the tests can load it.

import type { ReplayFields } from '../types/monitoring';

export interface ReplayView {
  // null for an older API that does not say
  protected: boolean | null;
  // "Protected", "Not protected" or "Not reported"
  label: string;
  // the API's own sentence or a fallback that says only what is known
  status: string;
  // the API's own warning that the counter jumped or null
  warning: string | null;
  // the API's own advice for the accept action or null
  recovery: string | null;
  // posts refused since the last one accepted
  refused: number;
  refusedAt: string | null;
  // "boot 7, seq 1042" or null before the first post
  lastPair: string | null;
  // from three refusals in a row the machine is locked out until an admin accepts a new counter
  lockedOut: boolean;
  // the warning is about a counter that was pushed up, which can mean the key is known to someone else
  keyAtRisk: boolean;
  // the action exists only for a protected machine and the API refuses anyone but an admin
  canAccept: boolean;
}

const STREAK = 3;

export function replayView(d: ReplayFields | null | undefined, isAdmin: boolean): ReplayView {
  const protectedFlag = typeof d?.replay_protected === 'boolean' ? d.replay_protected : null;
  const refused = typeof d?.replay_refused === 'number' && d.replay_refused > 0 ? d.replay_refused : 0;
  const warning = d?.replay_warning?.trim() || null;
  const pair = typeof d?.last_boot === 'number' && typeof d?.last_seq === 'number' ? `boot ${d.last_boot}, seq ${d.last_seq}` : null;
  return {
    protected: protectedFlag,
    label: protectedFlag === null ? 'Not reported' : protectedFlag ? (refused >= STREAK ? 'Protected, posts refused' : 'Protected') : 'Not protected',
    status: d?.replay_status?.trim() || (protectedFlag === null ? 'The API did not report replay protection for this machine.' : protectedFlag ? 'Every post must carry a newer boot and seq.' : 'This machine does not send boot and seq, so a captured post could be sent again.'),
    warning,
    recovery: d?.replay_recovery?.trim() || null,
    refused,
    refusedAt: d?.replay_refused_at ?? null,
    lastPair: pair,
    lockedOut: protectedFlag === true && refused >= STREAK,
    keyAtRisk: Boolean(warning || d?.counter_jump_note),
    canAccept: isAdmin && protectedFlag === true,
  };
}

// the API's sentences have no full stop, so one is added where a sentence sits among others
export function endSentence(text: string): string {
  const t = text.trim();
  return /[.!?]$/.test(t) ? t : `${t}.`;
}
