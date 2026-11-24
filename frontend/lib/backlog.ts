// a reading a gateway sent after an outage (docs/api-reference.md, "recorded_at and observed_at"). It is stored at the time it was
// taken, `quality.backlog` is true and `quality.received_at` says when it arrived. The rules and the model never judged it, so it is
// shown as late wherever readings are listed or drawn. No import, so the tests can load it.

interface QualityLike {
  quality?: { backlog?: boolean | null; received_at?: string | null } | null;
}

export function isBacklog(r: QualityLike): boolean {
  return r.quality?.backlog === true;
}

// how late it was: the time between when it was taken and when it arrived, in words. Null when either time is missing.
export function lateBy(takenAt: string, r: QualityLike): string | null {
  const got = r.quality?.received_at;
  if (!got) return null;
  const secs = (Date.parse(got) - Date.parse(takenAt)) / 1000;
  if (!Number.isFinite(secs) || secs < 0) return null;
  if (secs < 90) return `${Math.round(secs)} s`;
  const mins = Math.round(secs / 60);
  if (mins < 90) return `${mins} min`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.round(hours / 24)} d`;
}

export function lateWords(takenAt: string, r: QualityLike): string {
  const by = lateBy(takenAt, r);
  return by ? `Arrived late, ${by} after it was taken. Not judged by the rules or the model.` : 'Arrived late. Not judged by the rules or the model.';
}
