// one map from every state the product shows to a word, a shape and a tone. Status is never colour alone, so each
// entry has a shape name as well as a word. The components turn a tone into colour classes (components/ui/tone.ts)
// because Tailwind only scans app/ and components/.

export type Tone = 'success' | 'warning' | 'critical' | 'info' | 'neutral';
export type ShapeName = 'circle' | 'ring' | 'triangle' | 'diamond' | 'square';

export interface StatusInfo {
  word: string;
  shape: ShapeName;
  tone: Tone;
}

// machine status as the API sends it
export const MACHINE_STATUS = {
  online: { word: 'Online', shape: 'circle', tone: 'success' },
  offline: { word: 'Offline', shape: 'ring', tone: 'neutral' },
  warning: { word: 'Warning', shape: 'triangle', tone: 'warning' },
  fault: { word: 'Fault', shape: 'diamond', tone: 'critical' },
} as const satisfies Record<string, StatusInfo>;

// how recently the node posted. Late is shown only. Online means a post in the last few intervals, never "has some old reading".
export const LINK_STATE = {
  online: { word: 'Online', shape: 'circle', tone: 'success' },
  late: { word: 'Late', shape: 'triangle', tone: 'warning' },
  offline: { word: 'Offline', shape: 'ring', tone: 'neutral' },
} as const satisfies Record<string, StatusInfo>;

// what the machine is: its readings, apart from whether they are arriving. Unknown always sits beside its reason in words.
export const MACHINE_HEALTH = {
  healthy: { word: 'Healthy', shape: 'circle', tone: 'success' },
  warning: { word: 'Warning', shape: 'triangle', tone: 'warning' },
  fault: { word: 'Fault', shape: 'diamond', tone: 'critical' },
  unknown: { word: 'Unknown', shape: 'ring', tone: 'neutral' },
} as const satisfies Record<string, StatusInfo>;

// a reading the anomaly model has scored
export const READING_STATUS = {
  normal: { word: 'Normal', shape: 'circle', tone: 'success' },
  anomaly: { word: 'Anomaly', shape: 'diamond', tone: 'critical' },
} as const satisfies Record<string, StatusInfo>;

// alert and alert rule severity
export const ALERT_SEVERITY = {
  info: { word: 'Info', shape: 'square', tone: 'info' },
  warning: { word: 'Warning', shape: 'triangle', tone: 'warning' },
  critical: { word: 'Critical', shape: 'diamond', tone: 'critical' },
} as const satisfies Record<string, StatusInfo>;

export const TICKET_STATUS = {
  open: { word: 'Open', shape: 'square', tone: 'info' },
  in_progress: { word: 'In progress', shape: 'triangle', tone: 'warning' },
  closed: { word: 'Closed', shape: 'ring', tone: 'neutral' },
} as const satisfies Record<string, StatusInfo>;

export const TICKET_PRIORITY = {
  critical: { word: 'Critical', shape: 'diamond', tone: 'critical' },
  high: { word: 'High', shape: 'triangle', tone: 'warning' },
  medium: { word: 'Medium', shape: 'square', tone: 'info' },
  low: { word: 'Low', shape: 'ring', tone: 'neutral' },
} as const satisfies Record<string, StatusInfo>;

// every key in one flat lookup. The words that appear in two families (warning, critical) mean the same thing
// in both, so a single key is enough and StatusBadge can take one prop.
export const STATUS = {
  ...MACHINE_STATUS,
  ...LINK_STATE,
  ...MACHINE_HEALTH,
  ...READING_STATUS,
  ...ALERT_SEVERITY,
  ...TICKET_STATUS,
  ...TICKET_PRIORITY,
} as const satisfies Record<string, StatusInfo>;

export type StatusKey = keyof typeof STATUS;

const FALLBACK: StatusInfo = { word: 'Unknown', shape: 'ring', tone: 'neutral' };

export function isStatusKey(value: string): value is StatusKey {
  return Object.prototype.hasOwnProperty.call(STATUS, value);
}

// an unknown or missing value reads "Unknown" with a ring, never a blank
export function statusInfo(value: string | null | undefined): StatusInfo {
  return value && isStatusKey(value) ? STATUS[value] : FALLBACK;
}

// the order tickets are listed in, most urgent first
export const PRIORITY_ORDER = ['critical', 'high', 'medium', 'low'] as const;
