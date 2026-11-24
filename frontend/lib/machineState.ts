// what a machine is and how it is watched are two different facts and this file keeps them apart. The link is how
// recently the node posted: online, late or offline. The machine is what its readings say: healthy, warning, fault or
// unknown. A machine whose node has gone quiet is not "online" and it is not "healthy": it is unknown and the reason
// is said in words. No import, so the tests can load it.

export type LinkState = 'online' | 'late' | 'offline';
export type MachineHealth = 'healthy' | 'warning' | 'fault' | 'unknown';
// the four parts of the fleet bar: each machine is counted once, by the same state its own badge shows
export type FleetBucket = MachineHealth;

export interface HealthLike {
  faults?: Record<string, string> | null;
  // what the server found for itself in the latest post (stuck, out_of_range). Absent from an older API.
  server_faults?: Record<string, string> | null;
  not_fitted_by_firmware?: readonly string[] | null;
  reported_at?: string | null;
}

export interface DeviceLike {
  // sensor keys an admin marked as not fitted on this machine
  not_fitted?: readonly string[] | null;
  // sensors this firmware build does not carry, named by the firmware itself (an admin did not mark them)
  not_fitted_by_firmware?: readonly string[] | null;
  id: string;
  name?: string;
  status?: string | null;
  link_state?: string | null;
  seconds_since_last_post?: number | null;
  // how often the node posts, in seconds. The late and offline thresholds are 4 and 12 times this.
  expected_interval_s?: number | null;
  last_seen?: string | null;
  health?: HealthLike | null;
}

export interface AlertLike {
  device_id: string;
  severity?: string | null;
  // 'machine' (about the machine) or 'monitoring' (about how it is watched). An alert from an older API has none and is a machine alert.
  category?: string | null;
  resolved?: boolean;
}

// how many seconds of silence make a node late and offline when the API does not send link_state (an older API). They are
// the API's thresholds for a node that posts every 5 seconds: 4 and 12 intervals.
const LATE_AFTER_S = 20;
const OFFLINE_AFTER_S = 60;

// "42 s", "5 min", "3 h", "2 d": a length of time with no "ago", for "no reading for 16 h". A value that is not a number
// reads as an unknown length and never as "NaN d".
export function durationWords(seconds: number): string {
  if (!Number.isFinite(seconds)) return 'an unknown time';
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h`;
  return `${Math.round(h / 24)} d`;
}

const LINK_STATES = new Set(['online', 'late', 'offline']);

// seconds since the last post: the API's own figure when it sends one (the server's clock, so a wrong browser clock
// cannot change it), else worked out from last_seen
export function silenceSeconds(d: DeviceLike, now: number = Date.now()): number | null {
  if (typeof d.seconds_since_last_post === 'number' && Number.isFinite(d.seconds_since_last_post)) return d.seconds_since_last_post;
  if (d.seconds_since_last_post === null && d.link_state && LINK_STATES.has(d.link_state)) return null;
  if (!d.last_seen) return null;
  const t = Date.parse(d.last_seen);
  return Number.isNaN(t) ? null : Math.max(0, Math.round((now - t) / 1000));
}

// "just now", "5 min ago", "Never": the one wording of the last post, from the same figure the state's reason uses, so
// "no reading for 23 min" and "last post 23 min ago" cannot differ
export function lastPostWords(d: DeviceLike, now: number = Date.now()): string {
  const s = silenceSeconds(d, now);
  if (s === null) return 'Never';
  return s < 5 ? 'just now' : `${durationWords(s)} ago`;
}

const LINK_RANK: Record<LinkState, number> = { online: 0, late: 1, offline: 2 };

// the state the silence itself implies: late after 4 expected intervals and offline after 12. Null when the API sent no figure.
function impliedLink(d: DeviceLike): LinkState | null {
  const s = d.seconds_since_last_post;
  if (typeof s !== 'number' || !Number.isFinite(s)) return null;
  const interval = typeof d.expected_interval_s === 'number' && d.expected_interval_s > 0 ? d.expected_interval_s : 5;
  if (s > 12 * interval) return 'offline';
  if (s > 4 * interval) return 'late';
  return 'online';
}

// the one place a link state is decided. The API's word can lag (its sweep runs every 15 seconds and can stall), so when the
// age it sends in the same answer says the node is quieter than the word, the worse of the two wins and the page never reads
// "Link online" beside "last post 3 min ago".
export function linkOf(d: DeviceLike, now: number = Date.now()): LinkState {
  if (d.link_state === 'online' || d.link_state === 'late' || d.link_state === 'offline') {
    const implied = impliedLink(d);
    return implied && LINK_RANK[implied] > LINK_RANK[d.link_state] ? implied : d.link_state;
  }
  // an older API: status follows the link, but its "online" can be hours old, so the age decides
  if (d.status === 'offline') return 'offline';
  const silent = silenceSeconds(d, now);
  if (silent === null) return 'offline';
  if (silent > OFFLINE_AFTER_S) return 'offline';
  if (silent > LATE_AFTER_S) return 'late';
  return 'online';
}

function active(alerts: readonly AlertLike[], deviceId: string, severity: string): boolean {
  return alerts.some((a) => a.device_id === deviceId && !a.resolved && (a.category ?? 'machine') === 'machine' && a.severity === severity);
}

// what a read of the alerts amounts to. While the read has no answer, has failed or was cut off by its limit, a machine
// cannot be called healthy: "no alerts" would only mean "none that we saw". The reason is in words or null when the
// read is complete and current.
export interface AlertsRead {
  data: readonly unknown[] | null;
  error: string | null;
  // the X-Total-Count the API sent, when it sent one
  total?: number | null;
}

export function alertsGap(read: AlertsRead): string | null {
  if (!read.data) return read.error ? 'the alerts could not be loaded' : 'the alerts are still loading';
  if (read.error) return 'the alerts could not be refreshed';
  if (typeof read.total === 'number' && read.total > read.data.length) return `only ${read.data.length} of ${read.total} alerts were loaded`;
  return null;
}

// the rule behind the fleet bar, the legend, the health word and every machine's badge. They all call machineStatus, so
// the bar can never count as healthy a machine whose card says Unknown.
export function fleetBucket(d: DeviceLike, alerts: readonly AlertLike[], now: number = Date.now(), gap: string | null = null): FleetBucket {
  return machineStatus(d, alerts, now, gap).state;
}

export interface FleetSplit {
  healthy: number;
  warning: number;
  fault: number;
  unknown: number;
}

export function countFleet(devices: readonly DeviceLike[], alerts: readonly AlertLike[], now: number = Date.now(), gap: string | null = null): FleetSplit {
  const split: FleetSplit = { healthy: 0, warning: 0, fault: 0, unknown: 0 };
  for (const d of devices) split[fleetBucket(d, alerts, now, gap)] += 1;
  return split;
}

function fleetTotal(split: FleetSplit): number {
  return split.healthy + split.warning + split.fault + split.unknown;
}

// the one word for the whole fleet, from the same split the bar draws, so the word and the bar never disagree
export function fleetWord(split: FleetSplit): { word: 'Healthy' | 'Degraded' | 'Critical' | 'Unknown' | 'No machines'; tone: 'success' | 'warning' | 'critical' | 'neutral' } {
  const total = fleetTotal(split);
  if (total === 0) return { word: 'No machines', tone: 'neutral' };
  if (split.fault > 0) return { word: 'Critical', tone: 'critical' };
  if (split.unknown === total) return { word: 'Unknown', tone: 'neutral' };
  if (split.warning > 0 || split.unknown > 0) return { word: 'Degraded', tone: 'warning' };
  return { word: 'Healthy', tone: 'success' };
}

// the fleet in a sentence for the bar's text alternative and the line beside the word. A machine that is unknown is not
// counted healthy and the sentence says how many there are.
export function fleetSentence(split: FleetSplit): string {
  const total = fleetTotal(split);
  if (total === 0) return 'No machines yet';
  const unknown = split.unknown > 0 ? `, ${split.unknown} unknown` : '';
  return `${split.healthy} of ${total} ${total === 1 ? 'machine' : 'machines'} healthy${unknown}`;
}

// ---- sensors and their faults ----

// the keys the API stores (backend/app/services/sensor_map.py). The test reads that file and fails when one is missing
// here, so the two cannot drift again. fields are the telemetry columns a fault on that key stops.
interface SensorInfo {
  // a plain name for a sentence
  short: string;
  // the name with the part, for a heading
  full: string;
  fields: readonly string[];
}

const VIBRATION_FIELDS = ['fft_peak_hz', 'vib_clipping', 'vib_magnitude', 'vib_rms_x', 'vib_rms_y', 'vib_rms_z', 'vib_peak', 'stm32_vib_x', 'stm32_vib_y', 'stm32_vib_z'];
const NANO_FIELDS = ['nano_temp', 'nano_hum', 'nano_pres', 'nano_light', 'nano_moist', 'nano_water'];

// a Map and not an object, so a key such as "constructor" or "__proto__" from a node finds nothing instead of a function
const SENSORS = new Map<string, SensorInfo>([
  ['bme280', { short: 'air sensor', full: 'Air sensor (BME280)', fields: ['temperature', 'humidity', 'pressure'] }],
  ['mpu6050', { short: 'motion sensor', full: 'Motion sensor (MPU6050)', fields: ['vibration_x', 'vibration_y', 'vibration_z', 'gyro_x', 'gyro_y', 'gyro_z'] }],
  ['ina219', { short: 'power sensor', full: 'Power sensor (INA219)', fields: ['bus_voltage', 'current_ma', 'power_mw'] }],
  ['mlx90614', { short: 'infrared temperature sensor', full: 'Infrared temperature sensor (MLX90614)', fields: ['ir_temperature'] }],
  ['vl53l0x', { short: 'distance sensor', full: 'Distance sensor (VL53L0X)', fields: ['distance_mm'] }],
  ['mq2', { short: 'gas sensor', full: 'Gas sensor (MQ-2)', fields: ['gas_level', 'gas_alert'] }],
  ['as5600', { short: 'shaft sensor', full: 'Shaft sensor (AS5600)', fields: ['shaft_angle', 'shaft_rpm'] }],
  ['max4466', { short: 'sound sensor', full: 'Sound sensor (MAX4466)', fields: ['sound_level'] }],
  ['ldr', { short: 'light sensor', full: 'Light sensor (LDR)', fields: ['light_level'] }],
  ['ds18b20', { short: 'contact temperature sensor', full: 'Contact temperature sensor (DS18B20)', fields: ['contact_temp'] }],
  ['fc28', { short: 'moisture sensor', full: 'Moisture sensor (FC-28)', fields: ['moisture_level', 'water_detected'] }],
  ['nano_bme280', { short: 'air sensor on the Nano node', full: 'Air sensor on the Nano node (BME280)', fields: ['nano_temp', 'nano_hum', 'nano_pres'] }],
  ['nano_supply', { short: 'Nano node supply', full: 'Nano node supply', fields: [] }],
  ['stm32_mpu6050', { short: 'vibration sensor', full: 'Vibration sensor on the vibration node (MPU6050)', fields: VIBRATION_FIELDS }],
  ['nano_link', { short: 'link to the Nano node', full: 'Link to the Nano node', fields: NANO_FIELDS }],
  ['stm32_link', { short: 'link to the vibration node', full: 'Link to the vibration node', fields: VIBRATION_FIELDS }],
  ['supply', { short: '12 V supply', full: '12 V supply', fields: [] }],
]);

// the first name of stm32_link, which the API still accepts and stores under the new key
const ALIASES = new Map<string, string>([['stm32', 'stm32_link']]);

function canonical(key: string): string {
  return ALIASES.get(key) ?? key;
}

// every key the dashboard names, for the test and for the control that marks a sensor as not fitted
export function knownSensorKeys(): string[] {
  return [...SENSORS.keys()];
}

export function sensorFields(key: string): readonly string[] {
  return SENSORS.get(canonical(key))?.fields ?? [];
}

// a few states stop only some of a sensor's fields (backend/app/services/sensor_map.py, PARTIAL_STATE_FIELDS). The FC-28 unplugged
// reads zero moisture, so the moisture level is stopped and the water flag stays live: a flooded input must still raise its alarm.
const PARTIAL_STATE_FIELDS = new Map<string, readonly string[]>([['fc28|unplugged', ['moisture_level']]]);

export function partialStateEntries(): [string, readonly string[]][] {
  return [...PARTIAL_STATE_FIELDS];
}

// the fields a sensor stops while it is in a state
export function stateFields(key: string, state: string): readonly string[] {
  return PARTIAL_STATE_FIELDS.get(`${canonical(key)}|${state}`) ?? sensorFields(key);
}

// a plain name. A key the dashboard does not know reads "unknown sensor" with the raw key in brackets, so it is plain
// that the key is raw.
export function sensorName(key: string, withPart = false): string {
  const info = SENSORS.get(canonical(key));
  if (!info) return `unknown sensor (${key.slice(0, 32)})`;
  return withPart ? info.full : info.short;
}

// what each state the API stores means, in the words a maintenance person would use. "unknown" is what the API stores for
// a state it does not recognise.
const FAULT_WORDS = new Map<string, string>([
  ['missing', 'not answering'],
  ['stuck', 'stuck on one value'],
  ['out_of_range', 'reading outside what it can measure'],
  ['rate', 'changing faster than it can'],
  ['stale', 'giving old values'],
  ['intermittent', 'dropping in and out'],
  ['disagree', 'disagreeing with another sensor'],
  ['warming_up', 'still warming up'],
  ['not_fitted', 'not fitted'],
  ['unplugged', 'unplugged'],
  ['line_low', 'cut off, with its line held low'],
  ['silent', 'silent'],
  ['garbage', 'sending corrupt data'],
  ['one_way', 'answering in one direction only'],
]);

// the same states as a short label for a badge
const FAULT_LABELS = new Map<string, string>([
  ['missing', 'Not answering'],
  ['stuck', 'Stuck'],
  ['out_of_range', 'Out of range'],
  ['rate', 'Changing too fast'],
  ['stale', 'Old values'],
  ['intermittent', 'Dropping in and out'],
  ['disagree', 'Disagrees with another sensor'],
  ['warming_up', 'Warming up'],
  ['not_fitted', 'Not fitted'],
  ['unplugged', 'Cable unplugged'],
  ['line_low', 'Line held low'],
  ['silent', 'Silent'],
  ['garbage', 'Data arriving but corrupted'],
  ['one_way', 'Answers in one direction only'],
]);

export function knownFaultStates(): string[] {
  return [...FAULT_WORDS.keys()];
}

// a state the dashboard has no name for still shows, with the raw word, so a newer firmware is never hidden
export function faultWords(state: string): string {
  return FAULT_WORDS.get(state) ?? (state === 'unknown' ? 'in a state this dashboard has no name for' : `in a state this dashboard has no name for (${state.slice(0, 32)})`);
}

export function faultLabel(state: string): string {
  return FAULT_LABELS.get(state) ?? 'Unknown state';
}

// what a person standing at the machine should check for each state. The two the server finds for itself come first because the
// node never said anything: the readings alone gave it away.
const FAULT_ADVICE = new Map<string, string>([
  ['stuck', 'The value has not moved for longer than this sensor normally stays still, so the sensor may be frozen. Check that its wiring is firm and that the machine is really running, because a machine at rest can look the same.'],
  ['out_of_range', 'The sensor sent a number it cannot physically measure, so the value was dropped. Check the sensor\'s power and wiring for a loose or shorted connection.'],
  ['missing', 'The node cannot talk to this sensor. Check that it is plugged in and powered.'],
  ['rate', 'The value changed faster than the real thing could. Check for loose wiring or electrical noise near the sensor.'],
  ['stale', 'The sensor keeps giving old values. Check that it is powered and still taking readings.'],
  ['intermittent', 'The sensor keeps dropping out and coming back. Check its connector and cable for a loose contact.'],
  ['disagree', 'This sensor disagrees with another one that measures the same thing. Check which one is right and recalibrate or replace the other.'],
  ['unplugged', 'The input reads zero, as if its cable is not connected. Check the cable.'],
  ['line_low', 'The link is held low, as if the other node is cut off. Check its cable and power.'],
  ['silent', 'Nothing is coming over this link. Check that the other node is powered and running.'],
  ['garbage', 'Data is arriving but it is corrupted. Check the cable and the ground connection between the nodes.'],
  ['one_way', 'The satellite sends but does not answer. Check the wire back to it.'],
]);

export function faultAdvice(state: string): string | null {
  return FAULT_ADVICE.get(state) ?? null;
}

// warming up ends by itself and not fitted is a statement about the machine, not a failure: neither makes a machine unknown
const QUIET_STATES = new Set(['warming_up', 'not_fitted']);

// who found the fault: the node reported it, the server found it in the readings or both did
export type FaultSource = 'node' | 'server' | 'both';

export interface Fault {
  key: string;
  name: string;
  state: string;
  words: string;
  label: string;
  // true for a state that is not a failure
  quiet: boolean;
  source: FaultSource;
  // when the node and the server name different states for one sensor, the server's
  serverState?: string;
  // what an operator should check or null for a state that needs nothing
  advice: string | null;
}

// every sensor the node reported, plus the sensors an admin marked as not fitted. A not fitted sensor that the node never
// reports still shows as not fitted.
export function faultsOf(d: DeviceLike): Fault[] {
  const map = new Map<string, string>();
  const server = new Map<string, string>();
  for (const [key, state] of Object.entries(d.health?.server_faults ?? {})) server.set(canonical(key), String(state));
  for (const [key, state] of Object.entries(d.health?.faults ?? {})) map.set(canonical(key), String(state));
  // a fault only the server found is shown like the node's own and a sensor both named keeps the node's word
  for (const [key, state] of server) if (!map.has(key)) map.set(key, state);
  for (const key of d.not_fitted ?? []) map.set(canonical(key), 'not_fitted');
  // a sensor the firmware build itself does not carry is not fitted too and never a fault. An admin's own mark wins over the firmware's.
  const byFirmware = new Set<string>();
  for (const key of [...(d.not_fitted_by_firmware ?? []), ...(d.health?.not_fitted_by_firmware ?? [])]) {
    const k = canonical(String(key));
    if (!(d.not_fitted ?? []).map(canonical).includes(k)) {
      map.set(k, 'not_fitted');
      byFirmware.add(k);
    }
  }
  const nodeKeys = new Set(Object.keys(d.health?.faults ?? {}).map(canonical));
  return [...map].map(([key, state]) => {
    const serverState = server.get(key);
    const source: FaultSource = serverState === undefined ? 'node' : nodeKeys.has(key) ? 'both' : 'server';
    return {
      key,
      name: sensorName(key),
      state,
      words: faultWords(state),
      label: byFirmware.has(key) ? 'Not fitted (firmware build)' : faultLabel(state),
      quiet: QUIET_STATES.has(state),
      source: state === 'not_fitted' ? 'node' : source,
      ...(serverState !== undefined && serverState !== state ? { serverState } : {}),
      advice: faultAdvice(serverState !== undefined && source === 'server' ? serverState : state),
    };
  });
}

// the faults that make a machine unknown: the ones that are a failure
export function failingFaults(d: DeviceLike): Fault[] {
  return faultsOf(d).filter((f) => !f.quiet);
}

// the telemetry fields a set of faults stops, each with the fault behind it. A field one sensor makes and a link carries
// has the link's fault only when the sensor's own is absent, which is the order the API applies them in.
export function faultedFields(d: DeviceLike): Map<string, Fault> {
  const out = new Map<string, Fault>();
  for (const f of faultsOf(d)) for (const field of stateFields(f.key, f.state)) if (!out.has(field)) out.set(field, f);
  return out;
}

// readings newest first, each with the faults the node reported on it (the API's quality field). The time a fault began is
// the oldest reading of the unbroken run that carries it. A run that reaches the end of the rows only says "at least".
export function faultSince(rows: readonly { recorded_at: string; quality?: { faults?: Record<string, string> | null } | null }[], key: string): { at: string; atLeast: boolean } | null {
  let at: string | null = null;
  let broke = false;
  for (const r of rows) {
    if (r.quality?.faults && Object.hasOwn(r.quality.faults, key)) at = r.recorded_at;
    else {
      broke = true;
      break;
    }
  }
  return at ? { at, atLeast: !broke } : null;
}

// ---- the machine ----

export interface MachineStatusResult {
  state: MachineHealth;
  // in words, always present for unknown
  reason?: string;
}

// what the machine is. Unknown carries its reason: no reading for a length of time, never reported, a read of the alerts
// that is missing or cut off or a sensor that cannot be trusted. An active alert on the machine outranks all of those,
// because a real warning must show. There is no "since": the API says when the node last posted and not when a fault began.
export function machineStatus(d: DeviceLike, alerts: readonly AlertLike[], now: number = Date.now(), gap: string | null = null): MachineStatusResult {
  const link = linkOf(d, now);
  if (link === 'offline') {
    const silent = silenceSeconds(d, now);
    return { state: 'unknown', reason: silent === null ? 'it has never reported' : `no reading for ${durationWords(silent)}` };
  }
  if (active(alerts, d.id, 'critical')) return { state: 'fault' };
  if (active(alerts, d.id, 'warning')) return { state: 'warning' };
  if (gap) return { state: 'unknown', reason: gap };
  const faults = failingFaults(d);
  if (faults.length > 0) {
    const first = faults[0];
    const more = faults.length > 1 ? ` and ${faults.length - 1} more` : '';
    return { state: 'unknown', reason: `${first.name} ${first.words}${more}` };
  }
  return { state: 'healthy' };
}

export function monitoringAlertCount(alerts: readonly AlertLike[], deviceId?: string): number {
  return alerts.filter((a) => !a.resolved && a.category === 'monitoring' && (!deviceId || a.device_id === deviceId)).length;
}

// Wi-Fi signal strength in words. dBm is negative: closer to zero is stronger.
export function signalWords(rssi: number): string {
  if (rssi >= -60) return 'strong';
  if (rssi >= -75) return 'fair';
  return 'weak';
}

// free memory in kilobytes with a non-breaking space before the unit
export function memoryWords(bytes: number): string {
  return `${Math.round(bytes / 1024)} KB`;
}

// the firmware's reset reasons (firmware/esp32/esp32.ino, resetReasonName) in words. An unknown word is shown as it came.
const RESET_REASONS = new Map<string, string>([
  ['poweron', 'power switched on'],
  ['ext', 'reset button or external signal'],
  ['sw', 'restart requested by the software'],
  ['panic', 'crash in the firmware'],
  ['int_wdt', 'watchdog: the firmware stopped responding'],
  ['task_wdt', 'watchdog: a task stopped responding'],
  ['wdt', 'watchdog: the firmware stopped responding'],
  ['deepsleep', 'woke from deep sleep'],
  ['brownout', 'supply voltage dropped too low'],
  ['sdio', 'reset by the SDIO interface'],
  ['unknown', 'reason not known'],
]);

export function resetReasonWords(reason: string): string {
  return RESET_REASONS.get(reason) ?? reason;
}

export interface LinkCounters {
  ok?: number;
  crc?: number;
  gaps?: number;
  restarts?: number;
  st?: number;
  up?: number;
  vcc?: number;
}

// the serial links the hub reports, by name
const LINK_NAMES = new Map<string, string>([
  ['nano', 'Nano node'],
  ['stm32', 'Vibration node'],
]);

export function linkName(key: string): string {
  return LINK_NAMES.get(key) ?? `Link ${key.slice(0, 16)}`;
}

// a supply in millivolts as volts, "4.98 V", with a non-breaking space before the unit
export function supplyWords(millivolts: number): string {
  return `${(millivolts / 1000).toFixed(2)}\u00a0V`;
}

// the machine that posted most recently, for a panel that must open on one machine. A machine that has never posted comes
// last and the first of equals wins, so the choice is steady between polls.
export function mostRecentlyPosted<T extends DeviceLike>(devices: readonly T[], now: number = Date.now()): T | null {
  let best: T | null = null;
  let bestSeconds = Number.POSITIVE_INFINITY;
  for (const d of devices) {
    const s = silenceSeconds(d, now);
    const rank = s === null ? Number.MAX_SAFE_INTEGER : s;
    if (best === null || rank < bestSeconds) {
      best = d;
      bestSeconds = rank;
    }
  }
  return best;
}

// what a field reads right now, decided in one place for the chart headline, the machine card and the latest readings
// table. A value counts as current only when it is the field's newest value and is no older than three expected intervals
// (a hub forwards other nodes' fields in separate rows, so the newest row alone may lack a field the machine still reports);
// a field whose sensor is faulted or not fitted has no reading, whatever older rows hold.
export interface CurrentReading {
  status: 'value' | 'none' | 'fault' | 'stale';
  value: number | boolean | null;
  at: string | null;
  // in words, for every status but 'value'
  reason: string | null;
  // for 'stale': when the last value was recorded
  lastValueAt: string | null;
}

export function currentReading(
  rows: readonly { recorded_at: string }[],
  field: string,
  opts: { fault?: { name: string; words: string; state: string } | null; intervalS?: number; now?: number } = {},
): CurrentReading {
  const none = (status: CurrentReading['status'], reason: string, lastValueAt: string | null = null): CurrentReading => ({ status, value: null, at: null, reason, lastValueAt });
  if (opts.fault) {
    if (opts.fault.state === 'not_fitted') return none('fault', 'not fitted');
    if (opts.fault.state === 'warming_up') return none('fault', 'still warming up');
    return none('fault', `${opts.fault.name} ${opts.fault.words}`);
  }
  const hit = rows.find((r) => {
    const v = (r as unknown as Record<string, unknown>)[field];
    return typeof v === 'number' || typeof v === 'boolean';
  });
  if (!hit) return none('none', 'no reading in this window');
  const value = (hit as unknown as Record<string, unknown>)[field] as number | boolean;
  const now = opts.now ?? Date.now();
  const intervalMs = Math.max(5, opts.intervalS ?? 5) * 1000;
  const age = now - Date.parse(hit.recorded_at);
  if (Number.isFinite(age) && age > 3 * intervalMs) {
    return { status: 'stale', value: null, at: null, reason: `nothing for ${durationWords(age / 1000)}`, lastValueAt: hit.recorded_at };
  }
  return { status: 'value', value, at: hit.recorded_at, reason: null, lastValueAt: hit.recorded_at };
}

// the fields that cannot be trusted right now: the machine's faults (up to 15 seconds old by the time a poll lands) with the faults the
// newest reading itself carries. A number in the newest reading proves its sensor is working now, because the API stores a faulted
// sensor's fields as null, so a field with a number there is not faulted (unless the reading itself names its fault or it is marked
// not fitted).
export function faultedFieldsNow(d: DeviceLike, newest?: { quality?: { faults?: Record<string, string> | null } | null } | null): Map<string, Fault> {
  const fromRow = newest?.quality?.faults ?? {};
  const merged = faultedFields({
    ...d,
    health: { ...(d.health ?? {}), faults: { ...(d.health?.faults ?? {}), ...fromRow } },
  });
  if (!newest) return merged;
  const named = faultedFields({ id: d.id, health: { faults: fromRow } });
  for (const field of [...merged.keys()]) {
    const v = (newest as unknown as Record<string, unknown>)[field];
    if ((typeof v === 'number' || typeof v === 'boolean') && merged.get(field)?.state !== 'not_fitted' && !named.has(field)) merged.delete(field);
  }
  return merged;
}

// the sensors a node claimed were faulty in its latest post that the server did not act on, because no alert backed the claim. The
// value was kept and the rules judged it (docs/api-reference.md, "A fault claim stops its sensor only while an alert backs it"). Only the
// newest reading counts: an old claim says nothing about now. Rows come newest first.
export function notAppliedSensors(rows: readonly { quality?: { not_applied?: unknown } | null }[]): string[] {
  const raw = rows[0]?.quality?.not_applied;
  const names = Array.isArray(raw) ? raw : raw && typeof raw === 'object' ? Object.keys(raw) : [];
  return [...new Set(names.filter((n): n is string => typeof n === 'string' && n.length > 0).map((n) => n.slice(0, 32)))];
}
