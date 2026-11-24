import { describeBreach, parseAlertMessage } from '@/lib/alertGroups';

// a ticket raised from an alert before the title was written in words carries the alert's own text, "Alert: temperature is
// 38.672 (gt 30.0) on Walk Pump 1". It is shown through the same formatter the alerts page uses, "Temperature 38.7 °C over
// 30.0 °C on Walk Pump 1". Any other title is shown as it is.
export function ticketTitle(title: string | null): string {
  if (!title) return 'Untitled ticket';
  const text = title.replace(/^Alert:\s*/i, '');
  const parsed = parseAlertMessage(text);
  const words = parsed ? describeBreach({ metric: parsed.metric, latestValue: parsed.value, threshold: parsed.threshold, comparison: parsed.comparison }) : null;
  if (!words) return title;
  return parsed?.deviceName ? `${words} on ${parsed.deviceName}` : words;
}
