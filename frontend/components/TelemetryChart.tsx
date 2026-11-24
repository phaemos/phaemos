'use client';

// live readings for one device as small multiples: each sensor gets its own chart and scale, since pressure near 1000 hPa on
// the same axis as a 23 degree temperature flattens both into a line. The anomaly score comes first with the alert threshold
// drawn on it. Every chart is drawn against real time, so a silence shows as a gap, a faulted sensor shows as no reading and a
// reading pushed over the socket is drawn as soon as it arrives.

import { useState, useMemo, useCallback, useEffect, useDeferredValue } from 'react';
import { getTelemetry } from '../lib/api';
import { useWebSocketTelemetry } from '../hooks/useWebSocketTelemetry';
import type { Device, Telemetry, TelemetryBucket } from '../types/index';
import { RANGE_HOURS, bucketForRange, chartCaption, peakOverrides, pollIntervalMs, type Range } from '../lib/telemetryRange';
import { currentReading, faultedFieldsNow } from '../lib/machineState';
import { serverNow } from '../lib/serverClock';
import Panel from './ui/Panel';
import Segmented from './ui/Segmented';
import EmptyState from './ui/EmptyState';
import StatusBadge from './ui/StatusBadge';
import { Skeleton, SkeletonGroup } from './ui/Skeleton';
import InlineError from './dashboard/InlineError';
import ReadingChart, { type ChartMark, type ChartMetric, type ChartRow } from './dashboard/ReadingChart';
import ChartBoundary from './dashboard/ChartBoundary';
import { keyReadingsFrom, type KeyReading } from './dashboard/keyReadings';

const RANGES = [
  { value: '1h', label: '1h' },
  { value: '6h', label: '6h' },
  { value: '24h', label: '24h' },
  { value: '7d', label: '7d' },
] as const;

// one row of the chart: a single reading on the raw range or one bucket of readings on the others
type Row = Telemetry | TelemetryBucket;

// the next longer range, offered when the chosen one holds no readings
const WIDER: Record<Range, Range | null> = { '1h': '24h', '6h': '24h', '24h': '7d', '7d': null };

// the anomaly model's alert threshold, matching ANOMALY_THRESHOLD in the backend
const THRESHOLD = 0.7;

// the combined RMS of the vibration node's three axes or null when the reading lacks any of them
function rmsTotal(r: { vib_rms_x?: number | null; vib_rms_y?: number | null; vib_rms_z?: number | null }): number | null {
  const { vib_rms_x: x, vib_rms_y: y, vib_rms_z: z } = r;
  if (typeof x !== 'number' || typeof y !== 'number' || typeof z !== 'number') return null;
  return Math.sqrt(x * x + y * y + z * z);
}

const SCORE: ChartMetric = { key: 'anomaly_score', label: 'Anomaly score', unit: '', digits: 2 };

const METRICS: ChartMetric[] = [
  { key: 'vib_magnitude', label: 'Vibration', unit: 'g', digits: 2 },
  // the single most useful figure for a rotating machine: the three axes' RMS values combined as the square root of their sum of squares
  { key: 'vib_rms_total', label: 'Vibration strength (RMS)', unit: 'g', digits: 3 },
  { key: 'temperature', label: 'Temperature', unit: '°C', digits: 1 },
  { key: 'contact_temp', label: 'Contact temperature', unit: '°C', digits: 1 },
  { key: 'humidity', label: 'Humidity', unit: '%', digits: 1 },
  { key: 'moisture_level', label: 'Moisture', unit: 'counts', digits: 0 },
  { key: 'current_ma', label: 'Current', unit: 'mA', digits: 0 },
  { key: 'pressure', label: 'Pressure', unit: 'hPa', digits: 1 },
  { key: 'gas_level', label: 'Gas', unit: 'counts', digits: 0 },
  { key: 'fft_peak_hz', label: 'Vibration peak', unit: 'Hz', digits: 1 },
  { key: 'light_level', label: 'Light', unit: 'counts', digits: 0 },
];

// the derived chart takes its faults from the readings it combines
const FAULT_FIELD: Record<string, string> = { vib_rms_total: 'vib_rms_x' };

interface Props {
  deviceId: string;
  nodeType?: string;
  // the machine, for the interval its node posts at and the sensors that cannot be trusted. Without it the interval is the median step.
  device?: Pick<Device, 'expected_interval_s' | 'health' | 'not_fitted'> | null;
  // one chart per row, for narrow columns such as the comparison view
  compact?: boolean;
  // the chosen range, kept by the page (in its address). Left out, the chart keeps its own.
  range?: Range;
  onRangeChange?: (range: Range) => void;
  // called with the machine's headline readings each time the data refreshes, so a page can show them elsewhere
  onKeyReadings?: (readings: KeyReading[]) => void;
  // called with each reading the socket pushes, so a page can show it elsewhere at once
  onReading?: (reading: Telemetry) => void;
}

// the raw range (1h) asks for readings, newest first, up to this many. An hour is 720 at one every 5 seconds, so the
// limit is a guard rather than something the chart meets. Longer ranges ask for time buckets instead (see
// lib/telemetryRange.ts) because the same limit would cover only about two hours.
const LIMIT = 1500;
// the headline readings on a bucketed range come from this many of the newest raw readings
const LATEST = 20;
const LATEST_POLL_MS = 5000;
// a request that has not answered by now is given up, as in useApiResource
const TIMEOUT_MS = 20_000;

// two answers are the same rows when they have the same length and the same first and last row, comparing the newest row in full
// (a bucket that is still filling changes its values and keeps its time). Then the old array is kept, so nothing downstream is redone.
function sameRows(a: readonly Row[], b: readonly Row[]): boolean {
  if (a.length !== b.length) return false;
  if (a.length === 0) return true;
  return a[0].recorded_at === b[0].recorded_at && a[a.length - 1].recorded_at === b[b.length - 1].recorded_at && JSON.stringify(a[0]) === JSON.stringify(b[0]);
}

function withTimeout<T>(p: Promise<T>): Promise<T> {
  return Promise.race([p, new Promise<T>((_, reject) => setTimeout(() => reject(new Error('timeout')), TIMEOUT_MS))]);
}

// polls the window for the chosen range. The window start is worked out when each request is made, so it slides forward with
// the clock instead of staying where it was when the component mounted. A bucketed range polls more slowly because a bucket
// changes slowly. A tick is skipped while a request is still out and while the tab is hidden.
function useWindowedTelemetry(deviceId: string, range: Range, nodeType?: string) {
  const key = `${deviceId}|${range}|${nodeType ?? ''}`;
  const [state, setState] = useState<{ key: string; data: Row[]; failed: boolean; start: number | null; end: number | null }>({ key: '', data: [], failed: false, start: null, end: null });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    const bucket = bucketForRange(range);
    const fetchNow = async () => {
      if (inFlight) return;
      inFlight = true;
      const end = serverNow();
      const start = end - RANGE_HOURS[range] * 3_600_000;
      try {
        const data = await withTimeout(getTelemetry<Row>(deviceId, { limit: LIMIT, fromTs: new Date(start).toISOString(), nodeType, bucket }));
        // the window edges move in steps of a 120th of the window (30 s on the hour), so a poll that brings nothing new redraws nothing
        const step = (RANGE_HOURS[range] * 3_600_000) / 120;
        const qEnd = Math.floor(end / step) * step;
        if (!cancelled) {
          setState((prev) => {
            const same = prev.key === key && sameRows(prev.data, data);
            return { key, data: same ? prev.data : data, failed: false, start: qEnd - RANGE_HOURS[range] * 3_600_000, end: qEnd };
          });
        }
      } catch {
        // keep rows already shown for this window and flag the failure
        if (!cancelled) setState((prev) => ({ key, data: prev.key === key ? prev.data : [], failed: true, start: prev.start ?? start, end: prev.end ?? end }));
      } finally {
        inFlight = false;
      }
    };
    fetchNow();
    const timer = setInterval(() => { if (document.visibilityState === 'visible') fetchNow(); }, pollIntervalMs(bucket));
    const onVisible = () => { if (document.visibilityState === 'visible') fetchNow(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => { cancelled = true; clearInterval(timer); document.removeEventListener('visibilitychange', onVisible); };
  }, [deviceId, range, nodeType, key, attempt]);

  const current = state.key === key;
  return { data: current ? state.data : [], start: current ? state.start : null, end: current ? state.end : null, loading: !current, failed: state.failed && current, retry: () => setAttempt((n) => n + 1) };
}

// the newest few raw readings, polled every 5 seconds, for the headline readings while the chart itself shows
// buckets. A 30 minute average would be a poor "current" value. Null until the first answer for this machine.
function useLatestRaw(deviceId: string, nodeType: string | undefined, enabled: boolean) {
  const key = `${deviceId}|${nodeType ?? ''}`;
  const [state, setState] = useState<{ key: string; data: Telemetry[] } | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let inFlight = false;
    const fetchNow = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const data = await withTimeout(getTelemetry<Telemetry>(deviceId, { limit: LATEST, nodeType }));
        if (!cancelled) setState({ key, data });
      } catch {
        // the headline keeps its last values
      } finally {
        inFlight = false;
      }
    };
    fetchNow();
    const timer = setInterval(() => { if (document.visibilityState === 'visible') fetchNow(); }, LATEST_POLL_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, [deviceId, nodeType, key, enabled]);

  return enabled && state && state.key === key ? state.data : null;
}

export default function TelemetryChart({ deviceId, nodeType, device, compact = false, range: rangeProp, onRangeChange, onKeyReadings, onReading }: Props) {
  const [ownRange, setOwnRange] = useState<Range>('1h');
  const range = rangeProp ?? ownRange;
  const setRange = onRangeChange ?? setOwnRange;
  const bucket = bucketForRange(range);
  const { data: polledReadings, start, end, loading, failed, retry } = useWindowedTelemetry(deviceId, range, nodeType);
  const latestRaw = useLatestRaw(deviceId, nodeType, bucket !== null);

  // readings pushed over the socket since the last poll, newest first. They are state, so a pushed reading is drawn at once; the
  // next poll holds the same row and the id keeps it from being drawn twice.
  const [pushed, setPushed] = useState<{ deviceId: string; rows: Telemetry[] }>({ deviceId, rows: [] });
  const handleWsMessage = useCallback(
    (reading: Telemetry) => {
      // a reading from another node type is not part of this view, as the poll would not hold it either
      if (nodeType && reading.node_type && reading.node_type !== nodeType) return;
      // kept for the visible hour and not for a count: a node that posts every 2 seconds is 1800 readings an hour and dropping the
      // oldest at 50 would draw a false gap while the polls fail. The cap is only a guard.
      const cutoff = serverNow() - 3_600_000;
      setPushed((prev) => ({ deviceId, rows: [reading, ...(prev.deviceId === deviceId ? prev.rows : [])].filter((r) => Date.parse(r.recorded_at) >= cutoff).slice(0, 4000) }));
      onReading?.(reading);
    },
    [deviceId, nodeType, onReading],
  );
  const live = useWebSocketTelemetry(deviceId, { onMessage: handleWsMessage });

  // the clock for "how old is the newest value", moved every 5 seconds so a headline can go stale without a poll
  const [now, setNow] = useState(() => serverNow());
  useEffect(() => {
    const id = setInterval(() => setNow(serverNow()), 5000);
    return () => clearInterval(id);
  }, []);

  const readings = useMemo<Row[]>(() => {
    // pushed readings are single readings, so they only belong on the raw range. A bucketed range refetches instead
    if (bucket !== null) return polledReadings;
    const seen = new Set((polledReadings as Telemetry[]).map((r) => r.id));
    const windowStart = start ?? 0;
    const fresh = (pushed.deviceId === deviceId ? pushed.rows : []).filter((r) => !seen.has(r.id) && Date.parse(r.recorded_at) >= windowStart);
    return [...fresh, ...polledReadings];
  }, [polledReadings, pushed, deviceId, bucket, start]);

  const intervalS = device?.expected_interval_s ?? undefined;

  // the headline follows the newest raw reading, pushed or polled, never a bucket's average. On the raw range that is the chart's own
  // rows. On a longer range it is the few newest raw readings, with any pushed since. Each row carries the derived strength figure.
  const headRows = useMemo<Telemetry[]>(() => {
    const raw = bucket === null ? (readings as Telemetry[]) : [...(pushed.deviceId === deviceId ? pushed.rows : []), ...(latestRaw ?? [])];
    const seen = new Set<string>();
    return raw
      .filter((r) => !seen.has(r.id) && seen.add(r.id))
      .slice(0, 30)
      .map((r) => ({ ...r, vib_rms_total: rmsTotal(r) }) as Telemetry);
  }, [readings, bucket, pushed, deviceId, latestRaw]);

  // what the sensors can be trusted for: the machine's faults and the faults and values the newest reading itself carries
  const faulted = useMemo(() => faultedFieldsNow({ id: deviceId, not_fitted: device?.not_fitted, health: device?.health }, headRows[0] as never), [device, deviceId, headRows]);

  // held back while loading: after a device switch the hook still holds the previous machine's rows until the fetch lands
  useEffect(() => {
    if (loading) return;
    onKeyReadings?.(keyReadingsFrom(headRows, { faulted, intervalS, now }));
  }, [headRows, loading, onKeyReadings, faulted, intervalS, now]);

  const data = useMemo<ChartRow[]>(() => {
    const ordered = [...readings].reverse();
    return ordered.map((r, i) => {
      // a rolling mean of the last 10 scores: one flagged reading is expected now and then,
      // a rising average is the trend worth acting on
      const window = bucket !== null ? [] : ordered.slice(Math.max(0, i - 9), i + 1).map((x) => x.anomaly_score).filter((v): v is number => v != null);
      return {
        ...r,
        ...(bucket !== null ? peakOverrides(r) : {}),
        vib_rms_total: rmsTotal(r),
        t: Date.parse(r.recorded_at),
        score_trend: window.length ? window.reduce((a, b) => a + b, 0) / window.length : null,
      };
    });
  }, [readings, bucket]);

  const win = useMemo(() => {
    const newest = data.length ? data[data.length - 1].t : 0;
    // the right edge is the present: the time of the poll or of a reading pushed since
    return { start: start ?? 0, end: Math.max(end ?? 0, newest) };
  }, [start, end, data]);

  // the charts redraw from deferred values, so a window that moved or new rows are drawn in slices the browser can interrupt and no
  // single task holds the page for a dozen charts at once
  const drawWin = useDeferredValue(win);
  const drawData = useDeferredValue(data);

  const shown = METRICS.filter((m) => data.some((r) => r[m.key] !== null && r[m.key] !== undefined));
  const hasScore = data.some((r) => r.anomaly_score !== null && r.anomaly_score !== undefined);
  const newestRow = readings[0] as (Row & { quality?: { scoring_error?: string | null } | null }) | undefined;
  const scoringError = newestRow?.quality?.scoring_error ?? null;
  const empty = !hasScore && !scoringError && shown.length === 0 && !loading;
  const wider = WIDER[range];
  // the gap rule is three of the larger of the bucket and the node's own interval: a node that posts every 300 s is not "silent" on the 6h
  // range between two of its own posts
  const gapS = Math.max(bucket ?? 0, intervalS ?? 0);
  const intervalMs = gapS > 0 ? gapS * 1000 : null;

  // what a chart says it reads now: the same decision the cards and the readings table make, on the newest raw readings
  const currentFor = (key: string) => currentReading(headRows, key, { fault: faulted.get(FAULT_FIELD[key] ?? key) ?? null, intervalS, now });

  // readings beyond the sensor's range are marked on the vibration strength line, with words
  const clipMarks: ChartMark[] = useMemo(
    () =>
      data
        .filter((r) => r.vib_clipping === true && typeof r.vib_rms_total === 'number')
        .slice(-20)
        .map((r) => ({ t: r.t, value: r.vib_rms_total as number, text: "Beyond the sensor's range, so readings are cut off" })),
    [data],
  );

  // a reading a gateway sent after an outage is stored at the time it was taken and was never judged. It is marked on each line where it
  // was observed, with words and by a square so the mark does not rely on colour. The newest 20 are marked.
  const lateMarks = useCallback(
    (key: string): ChartMark[] =>
      data
        .filter((r) => (r.quality as { backlog?: boolean } | null | undefined)?.backlog === true && typeof r[key] === 'number')
        .slice(-20)
        .map((r) => ({ t: r.t, value: r[key] as number, text: 'Arrived late from a gateway backlog, so the rules and the model never judged it', kind: 'late' as const })),
    [data],
  );

  // say only what is true: what each point is and over which window
  const caption = chartCaption({
    range,
    bucket,
    loading,
    count: readings.length,
    windowStart: start === null ? null : new Date(start),
    windowEnd: end === null ? null : new Date(end),
    oldest: readings[readings.length - 1]?.recorded_at,
    newest: readings[0]?.recorded_at,
    cut: polledReadings.length >= LIMIT,
    failed,
  });

  return (
    <Panel
      title="Live readings"
      description={caption}
      actions={
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {/* a shape and a word, never colour alone. The reason for a stopped socket also says the page still refreshes by polling. */}
          <span title={live.reason ?? undefined}>
            <StatusBadge status={live.state === 'live' ? 'online' : live.state === 'reconnecting' ? 'late' : 'offline'} label={live.state === 'live' ? 'Live updates' : live.state === 'reconnecting' ? 'Reconnecting' : 'Live updates stopped'} />
          </span>
          <Segmented label="Time range" hideLabel options={RANGES} value={range} onChange={setRange} />
        </div>
      }
    >
      {live.state === 'stopped' && <p className="mb-3 max-w-[72ch] text-base text-surface-800 dark:text-surface-200">{live.reason}</p>}
      {failed && (
        <div className="mb-3">
          <InlineError message={readings.length > 0 ? 'Readings could not be refreshed. The chart may be out of date.' : 'Readings could not be loaded.'} onRetry={retry} />
        </div>
      )}
      {loading ? (
        <SkeletonGroup label="Loading the readings" className="space-y-6">
          <Skeleton className="h-52 w-full" />
          <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-3">
            <Skeleton className="h-44 w-full" />
            <Skeleton className="h-44 w-full" />
            <Skeleton className="h-44 w-full" />
          </div>
        </SkeletonGroup>
      ) : empty && failed ? null : empty ? (
        <EmptyState
          heading={`No readings in the last ${range}`}
          subMessage={
            wider
              ? 'The node may be quiet or switched off. Try a longer range. Check that it is powered and posting.'
              : 'The node has sent nothing for a week. Check that it is powered and can reach the API.'
          }
          action={wider ? { label: `Show the last ${wider}`, onClick: () => setRange(wider) } : { label: 'Open machine page', href: `/devices/${deviceId}` }}
        />
      ) : (
        <div className={`grid gap-x-6 gap-y-8 ${compact ? '' : 'sm:grid-cols-2 xl:grid-cols-3'}`}>
          {(hasScore || scoringError) && (
            <ChartBoundary name={SCORE.label}>
              <ReadingChart
                metric={SCORE}
                data={drawData}
                window={drawWin}
                intervalMs={intervalMs}
                current={currentFor('anomaly_score')}
                threshold={THRESHOLD}
                bucket={bucket}
                wide={!compact}
                notice={scoringError ? `The model could not be used, so this reading has no score: ${scoringError}.` : null}
                className={compact ? '' : 'sm:col-span-2 xl:col-span-3'}
              />
            </ChartBoundary>
          )}
          {shown.map((m) => (
            <ChartBoundary key={m.key} name={m.label}>
              <ReadingChart metric={m} data={drawData} window={drawWin} intervalMs={intervalMs} current={currentFor(m.key)} bucket={bucket} marks={m.key === 'vib_rms_total' ? [...clipMarks, ...lateMarks(m.key)] : lateMarks(m.key)} />
            </ChartBoundary>
          ))}
        </div>
      )}
    </Panel>
  );
}
