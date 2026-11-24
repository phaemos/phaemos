// the shapes the alert, model and replay routes return beyond the older machine and alert fields (docs/api-reference.md);
// they live in their own file so the shared types in index.ts only gain the fields that point at them.

// the figures behind a model alert. The server writes a flat object: the counts of its window and, when one sensor carried the
// score, that sensor with its latest value. A value outside its usual range carries `range` as [low, high] (older code and the
// alert schema comment call the same figures low and high), a slow change carries `expected` and `minutes` instead.
export interface AlertEvidence {
  readings?: number;
  over_boundary?: number;
  median?: number | null;
  window_s?: number;
  sensor?: string;
  value?: number;
  direction?: 'above' | 'below' | string;
  range?: [number, number] | number[];
  low?: number;
  high?: number;
  expected?: number;
  minutes?: number;
}

// the model's state for one machine, in the device read
export type DeviceModelState = 'ready' | 'learning' | 'legacy' | 'none' | 'error';

export interface DeviceModel {
  state: DeviceModelState | string;
  scope?: 'machine' | 'node_type' | 'general' | null;
  hours_collected?: number | null;
  hours_needed?: number | null;
  false_alerts_per_week?: number | null;
  trained_at?: string | null;
  // when the last retrain refused this machine's own model and why. Null when it did not.
  refused_at?: string | null;
  refusal?: string | null;
}

// the replay protection fields of the device read
export interface ReplayFields {
  replay_protected?: boolean;
  last_boot?: number | null;
  last_seq?: number | null;
  replay_refused?: number;
  replay_refused_at?: string | null;
  replay_status?: string | null;
  replay_warning?: string | null;
  replay_recovery?: string | null;
  counter_jump_at?: string | null;
  counter_jump_note?: string | null;
}

// GET /ml/status
export interface MlFaultTrial {
  kind: string;
  applicable?: boolean;
  trials?: number;
  caught?: number;
  median_delay_s?: number | null;
  delays_s?: number[];
}

export interface MlDetection {
  missed_share?: number | null;
  trials?: number;
  caught?: number;
  faults?: MlFaultTrial[];
}

export interface MlRetrainModel {
  key: string;
  scope?: string;
  label?: string;
  state: 'ready' | 'refused' | 'learning' | string;
  message?: string;
  rows_fit?: number;
  rows_heldout?: number;
  clean_hours?: number;
  span_hours?: number;
  rows_refused?: Record<string, number>;
  false_alerts_per_week?: number | null;
  alerts_heldout?: number;
  heldout_hours?: number;
  budget_per_week?: number;
  quantile?: number;
  tightenings?: number;
  boundary?: number;
  detection?: MlDetection | null;
}

export interface MlRetrain {
  status: 'trained' | 'refused' | string;
  trigger?: 'manual' | 'nightly' | string;
  finished_at?: string | null;
  summary?: string;
  models?: MlRetrainModel[];
  learning?: string[];
}

export interface MlStatusModel {
  key: string;
  scope?: string;
  legacy?: boolean;
  false_alerts_per_week?: number | null;
  features?: string[];
}

export interface MlStatus {
  state: 'none' | 'ok' | 'legacy' | 'error' | string;
  trained_at?: string | null;
  models?: MlStatusModel[];
  last_retrain?: MlRetrain | null;
  schedule?: { nightly_utc?: string | null; next_at?: string | null } | null;
}
