import { metricLabel as readingLabel } from '@/lib/alertMetrics';
import { describeBreach, parseAlertMessage } from '@/lib/alertGroups';
import { monitoringAlertText } from '@/lib/alertText';
import { faultWords, sensorName } from '@/lib/machineState';
import { evidenceWords } from '@/lib/anomalyEvidence';
import { isModelAlert } from '@/lib/alertLife';

// one alert in words a reader can use: a machine alert as "Temperature 38.7 °C over 30.0 °C" and a monitoring alert with
// its sensor named in plain words. A message that matches neither is shown as the API wrote it.
export function alertText(alert: { message: string | null; category?: string | null; sensor_key?: string | null; kind?: string | null; rule_id?: string | null; severity?: string | null; evidence?: unknown }): string {
  // the model's alert says which sensor stood out and where its value sits against the usual range or that the reading was flagged as a whole
  if (isModelAlert({ kind: alert.kind, rule_id: alert.rule_id ?? null, category: alert.category, message: alert.message })) return evidenceWords(alert.evidence, alert.severity);
  // an alert about vibration beyond the sensor's range is a machine alert with its own kind
  if (alert.category === 'monitoring' || alert.kind === 'clipping' || alert.kind === 'board_mismatch') {
    return monitoringAlertText(alert.message, alert.sensor_key, {
      sensor: (key) => sensorName(key),
      state: (state) => faultWords(state),
      metric: (field) => readingLabel(field).toLowerCase(),
    }, alert.kind);
  }
  const parsed = parseAlertMessage(alert.message);
  const words = parsed ? describeBreach({ metric: parsed.metric, latestValue: parsed.value, threshold: parsed.threshold, comparison: parsed.comparison }) : null;
  return words ?? alert.message ?? 'No message';
}

// where a monitoring alert about a sensor leads: the machine's Monitoring health section, which names the sensor and says how
// long it has been in fault. Other alerts lead to the machine page.
export function alertMachineHref(alert: { device_id: string; category?: string | null }): string {
  return alert.category === 'monitoring' ? `/devices/${alert.device_id}#monitoring-health` : `/devices/${alert.device_id}`;
}
