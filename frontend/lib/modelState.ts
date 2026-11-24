// what the anomaly model is doing, for a machine and for the fleet, in words an operator can act on. The figures come from the device
// read (`model`) and from GET /ml/status (docs/api-reference.md, "ML"). A machine in learning is not scored and raises no anomaly
// alert and every sentence here that could hide that says it. No import, so the tests can load it.

export interface ModelLike {
  state?: string | null;
  scope?: string | null;
  hours_collected?: number | null;
  hours_needed?: number | null;
  false_alerts_per_week?: number | null;
  trained_at?: string | null;
  refusal?: string | null;
}

export type ModelKind = 'ready' | 'learning' | 'legacy' | 'none' | 'refused' | 'error' | 'unknown';

export interface ModelView {
  kind: ModelKind;
  // the short word for a badge
  label: string;
  // one sentence that says what it means for alerts
  detail: string;
  // the key in lib/status.ts whose shape and tone the badge borrows. The word is always shown, so colour is never the only signal.
  status: 'healthy' | 'open' | 'warning' | 'unknown' | 'fault';
  // true when the model page explains more than this line can
  toModelPage: boolean;
}

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

function hours(n: number): string {
  const r = Math.round(n * 10) / 10;
  return Number.isInteger(r) ? String(r) : r.toFixed(1);
}

const SCOPE_WORDS: Record<string, string> = {
  machine: 'its own model',
  node_type: 'the model for its node type',
  general: 'the general model',
};

export const NO_ALERTS_WHILE_LEARNING = 'A machine in learning is not scored and raises no anomaly alerts. Alert rules still work.';

// `refusal` is the message of a model this machine's last retrain refused, when there is one
export function modelView(model: ModelLike | null | undefined, fallbackRefusal?: string | null): ModelView {
  // the device's own refusal wins. The retrain's message for the machine is the fallback for an API that does not send it.
  const refusal = model?.refusal || fallbackRefusal || null;
  if (!model || typeof model.state !== 'string') {
    return { kind: 'unknown', label: 'Model not reported', detail: 'The API did not say what the model is doing for this machine.', status: 'unknown', toModelPage: false };
  }
  switch (model.state) {
    case 'ready': {
      const scope = model.scope && Object.hasOwn(SCOPE_WORDS, model.scope) ? SCOPE_WORDS[model.scope] : 'a model';
      return { kind: 'ready', label: 'Ready', detail: `Scoring this machine with ${scope}.`, status: 'healthy', toModelPage: false };
    }
    case 'learning': {
      const got = finite(model.hours_collected) ? hours(model.hours_collected) : null;
      const need = finite(model.hours_needed) ? hours(model.hours_needed) : null;
      const progress = got !== null && need !== null ? `Learning, ${got} ${got === '1' ? 'hour' : 'hours'} of ${need} collected` : 'Learning';
      return { kind: 'learning', label: progress, detail: NO_ALERTS_WHILE_LEARNING, status: 'open', toModelPage: false };
    }
    case 'legacy':
      return { kind: 'legacy', label: 'Legacy model', detail: 'A model from before this version is scoring with its old meaning until the next retrain.', status: 'warning', toModelPage: true };
    case 'error':
      return { kind: 'error', label: 'Model error', detail: 'The model file will not load, so this machine is not scored. An admin can retrain from the model page.', status: 'fault', toModelPage: true };
    case 'none':
      if (refusal) return { kind: 'refused', label: 'No model: refused', detail: `The last retrain refused this machine's model. ${refusal}`, status: 'warning', toModelPage: true };
      return { kind: 'none', label: 'No model', detail: 'No model is in service for this machine, so it raises no anomaly alerts.', status: 'unknown', toModelPage: true };
    default:
      return { kind: 'unknown', label: 'Model not reported', detail: 'The API named a model state this dashboard does not know.', status: 'unknown', toModelPage: false };
  }
}

interface RetrainModelLike {
  key: string;
  state?: string;
  message?: string;
}

interface StatusLike {
  last_retrain?: { models?: readonly RetrainModelLike[] | null } | null;
}

// the message of the model the last retrain refused for one machine. The model's key in the retrain is "machine:<id>".
export function refusalFor(status: StatusLike | null | undefined, deviceId: string): string | null {
  const m = status?.last_retrain?.models?.find((x) => x.key === `machine:${deviceId}`);
  return m && m.state === 'refused' ? m.message || 'No reason was given.' : null;
}

export interface FalseAlertRow {
  rate: number | null;
  budget: number;
  // over the budget of one a week
  over: boolean;
  words: string;
}

export const FALSE_ALERT_BUDGET = 1;

// measured on healthy readings the model did not train on, per machine per week. Beyond the budget the model is refused.
export function falseAlertRow(rate: number | null | undefined, budget: number | null | undefined): FalseAlertRow {
  const b = finite(budget) && budget > 0 ? budget : FALSE_ALERT_BUDGET;
  if (!finite(rate)) return { rate: null, budget: b, over: false, words: `Not measured. The budget is ${b} a week.` };
  const shown = rate === 0 ? '0' : rate < 10 ? rate.toFixed(1) : rate.toFixed(0);
  return { rate, budget: b, over: rate > b, words: `${shown} false alerts a week against a budget of ${b}` };
}

const REFUSED_ROWS: Record<string, string> = {
  maintenance: 'in a maintenance window',
  sensor_fault: 'with a sensor fault',
  machine_alert: 'while a machine alert was open',
  link: 'beside a gap in the posts',
};

// the readings left out of training and why, biggest first
export function rowsRefusedWords(rows: Record<string, number> | null | undefined): string | null {
  const parts = Object.entries(rows ?? {})
    .filter(([, n]) => finite(n) && n > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([why, n]) => `${n.toLocaleString('en-GB')} ${Object.hasOwn(REFUSED_ROWS, why) ? REFUSED_ROWS[why] : why.replace(/_/g, ' ')}`);
  return parts.length ? `Left out of training: ${parts.join(', ')}.` : null;
}

export function detectionWords(d: { trials?: number; caught?: number } | null | undefined): string | null {
  if (!d || !finite(d.trials) || d.trials <= 0 || !finite(d.caught)) return null;
  const share = Math.round((d.caught / d.trials) * 100);
  return `Found ${d.caught} of ${d.trials} faults injected into healthy readings (${share} per cent). At least half are needed.`;
}

interface RetrainLike {
  status?: string;
  trigger?: string;
  finished_at?: string | null;
  models?: readonly RetrainModelLike[] | null;
  learning?: readonly string[] | null;
}

export function retrainHeadline(r: RetrainLike | null | undefined): string {
  if (!r) return 'No retrain has run yet.';
  const who = r.trigger === 'manual' ? 'by an admin' : r.trigger === 'nightly' ? 'by the nightly schedule' : '';
  if (r.status === 'trained') return `The last retrain${who ? ' ' + who : ''} saved new models.`;
  if (r.status === 'refused') return `The last retrain${who ? ' ' + who : ''} saved nothing. The models already in service are untouched.`;
  return `The last retrain${who ? ' ' + who : ''} ended with a result this dashboard does not know.`;
}

export interface RetrainCounts {
  ready: number;
  refused: number;
  learning: number;
}

export function retrainCounts(r: RetrainLike | null | undefined): RetrainCounts {
  const out = { ready: 0, refused: 0, learning: 0 };
  for (const m of r?.models ?? []) {
    if (m.state === 'ready') out.ready += 1;
    else if (m.state === 'refused') out.refused += 1;
    else if (m.state === 'learning') out.learning += 1;
  }
  return out;
}

// "04:10" and "04:10 UTC" both read "04:10 UTC". Anything else is shown as the API sent it.
export function nightlyWords(nightly: string | null | undefined): string | null {
  if (!nightly || typeof nightly !== 'string') return null;
  const t = nightly.trim();
  return /utc/i.test(t) ? t : `${t} UTC`;
}

// the explanation of the top-level state of the model file
export function fileStateWords(state: string | null | undefined): string {
  switch (state) {
    case 'ok': return 'Models are in service.';
    case 'none': return 'No model file exists yet, so no machine is scored. A retrain makes one once machines have a day of clean readings.';
    case 'legacy': return 'The model file is from before this version. It still scores, with its old meaning, until a retrain replaces it.';
    case 'error': return 'The model file will not load, so no machine is scored. Run a retrain to replace it.';
    default: return 'The API named a model file state this dashboard does not know.';
  }
}

// the answer to a retrain request. The result is not in the answer: it is read from the status route when the run finishes.
export function retrainRefusalWords(status: number | undefined, detail: string | null): string {
  if (status === 429) return detail ?? 'A retrain ran recently. Try again later.';
  if (status === 403) return 'Only admins can start a retrain.';
  return detail ?? 'The retrain could not be started.';
}

interface NamedModel {
  key: string;
  scope?: string;
  label?: string;
}

// "press-01" for a machine's own model, "esp32 node type" for a node type's and "general model" for the fallback
export function modelName(m: NamedModel): string {
  if (m.label) return m.label;
  if (m.scope === 'node_type') return `${m.key} node type`;
  if (m.scope === 'general' || m.key === 'general') return 'General model';
  return m.key.replace(/^machine:/, 'machine ');
}

// the state of one model in the last retrain: a word and the lib/status.ts key whose shape it borrows
export function retrainStateBadge(state: string | undefined): { label: string; status: ModelView['status'] } {
  if (state === 'ready') return { label: 'Accepted', status: 'healthy' };
  if (state === 'refused') return { label: 'Refused', status: 'warning' };
  if (state === 'learning') return { label: 'Learning', status: 'open' };
  return { label: 'Unknown', status: 'unknown' };
}

// whether a retrain run, asked for at `askedAt`, has finished: the status route then holds a retrain that ended after the request
// began. `baseline` is the finished_at the page saw before asking, so a result that was already there is never mistaken for the new one.
export function retrainFinished(finishedAt: string | null | undefined, baseline: string | null | undefined, askedAt: number): boolean {
  if (!finishedAt || finishedAt === baseline) return false;
  const t = Date.parse(finishedAt);
  return Number.isFinite(t) && t >= askedAt - 5000;
}
