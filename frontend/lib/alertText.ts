// the words of a monitoring alert for a reader. The API writes these alerts as sentences (backend/app/services/liveness_service.py
// and health_service.py): a failed sensor, a silent node, a restart loop and a model with no scored reading. They carry raw
// sensor keys, raw state codes and a sentence fixed at the moment the alert opened ("has not reported for 2 minutes"), which
// is wrong an hour later. This turns each into plain words and leaves any other message as it came. The names come in as
// functions so this file has no import and the Node tests can load it.

export interface AlertNames {
  // "air sensor" for bme280
  sensor: (key: string) => string;
  // "not answering" for missing
  state: (state: string) => string;
  // "humidity" for humidity
  metric: (field: string) => string;
}

const upper = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

const INTERMITTENT = /is intermittent \(it changed between working and faulty (\d+) times in the last hour\)/;
const SENSOR_STATE = /\bis [^()]*\(([a-z_0-9]+)\)\s*(\(resolved:[^)]*\))?\s*$/;
const SILENT = /has not reported for \d+ minutes?\b/;
const BACK_ONLINE = /\((back online after [^)]+)\)/;
const RESTARTS = /has restarted (\d+) times in (\d+) minutes/;
const NO_SCORE = /has had no scored reading for (\d+) minutes: the model is missing (.+?)\.?\s*$/;

export type AlertKind = 'offline' | 'reset_loop' | 'unscored' | 'sensor' | 'clipping' | string | null | undefined;

const CLIPPING_RESOLVED = /\(resolved[^)]*\)\s*$/;

// `kind` is what the API says the alert is about (docs/api-reference.md), so the words are chosen from it and not guessed from the
// message. A message the kind does not explain is shown as it came.
export function monitoringAlertText(message: string | null | undefined, sensorKey: string | null | undefined, names: AlertNames, kind?: AlertKind): string {
  const text = (message ?? '').trim();
  if (!text) return 'No message';

  if (kind === 'clipping') {
    return `Vibration is beyond the sensor's range, so its readings are cut off${CLIPPING_RESOLVED.test(text) ? ' (resolved: it is back inside the range)' : ''}`;
  }
  if (kind === 'board_mismatch') return 'The firmware image on this node does not match its board';
  if (kind === 'offline') {
    const back = BACK_ONLINE.exec(text);
    return back ? `Stopped reporting (${back[1]})` : 'Stopped reporting';
  }
  if (kind === 'reset_loop') {
    const restarts = RESTARTS.exec(text);
    return restarts ? `Restarted ${restarts[1]} times in ${restarts[2]} minutes` : 'Restarting repeatedly';
  }
  if (sensorKey) {
    const sensor = upper(names.sensor(sensorKey));
    const dropping = INTERMITTENT.exec(text);
    if (dropping) return `${sensor} ${names.state('intermittent')}: it changed between working and faulty ${dropping[1]} times in the last hour`;
    const state = SENSOR_STATE.exec(text);
    if (state) return `${sensor} ${names.state(state[1])}${state[2] ? ' (resolved: the sensor reported ok for a minute)' : ''}`;
    return text.replace(/^[^:]*:\s*/, '').replace(sensorKey, names.sensor(sensorKey));
  }

  if (kind !== 'sensor' && SILENT.test(text)) {
    const back = BACK_ONLINE.exec(text);
    return back ? `Stopped reporting (${back[1]})` : 'Stopped reporting';
  }
  const restarts = RESTARTS.exec(text);
  if (restarts) return `Restarted ${restarts[1]} times in ${restarts[2]} minutes`;
  const noScore = NO_SCORE.exec(text);
  if (noScore) {
    const inputs = noScore[2].split(/,\s*(?:and\s+)?/).map((f) => names.metric(f.trim()));
    const list = inputs.length > 1 ? `${inputs.slice(0, -1).join(', ')} and ${inputs[inputs.length - 1]}` : inputs[0];
    return `No scored reading for ${noScore[1]} minutes. The model is missing ${list}`;
  }
  return text;
}
