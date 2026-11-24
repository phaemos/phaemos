'use client';

import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { CartesianGrid, Line, LineChart, ReferenceArea, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { bucketLabel, bucketTooltip, fullStamp, maxTicksFor, tickLabel, tickStyle } from '../../lib/telemetryRange';
import { breakAtGaps, chooseTimeTicks, decimateSeries, dedupeTicks, findGaps, gapThresholdMs, spanWords, type Gap } from '../../lib/chartSeries';
import { formatReading } from '@/lib/units';
import { plural } from '@/lib/format';
import type { CurrentReading } from '@/lib/machineState';

export interface ChartMetric {
  key: string;
  label: string;
  unit: string;
  digits: number;
}

export interface ChartRow {
  // when the row was recorded, in milliseconds. The axis is real time.
  t: number;
  score_trend?: number | null;
  [key: string]: string | number | boolean | object | null | undefined;
}

// a point worth marking on the line, with the words that name it (for example a reading beyond the sensor's range)
export interface ChartMark {
  t: number;
  value: number;
  text: string;
  // 'late' is a reading a gateway sent after an outage: it is drawn where it was taken, as an outlined square and was never judged by
  // the rules or the model. Absent is a reading beyond the sensor's range, drawn as a filled diamond.
  kind?: 'range' | 'late';
}

// the colours are custom properties set per theme in globals.css (--chart-*), so this file holds no colour of its own

interface TipProps {
  active?: boolean;
  payload?: ReadonlyArray<{ name?: unknown; value?: unknown; dataKey?: unknown; payload?: { reading_count?: unknown } }>;
  label?: unknown;
  unit: string;
  digits: number;
  // seconds, set when each point is a bucket of readings rather than one reading
  bucket?: number | null;
}

function ChartTooltip({ active, payload, label, unit, digits, bucket }: TipProps) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-md border border-surface-500 bg-surface-0 px-3 py-2 text-meta text-surface-900 dark:bg-surface-900 dark:text-surface-50">
      <p className="tnum text-surface-700 dark:text-surface-300">{typeof label === 'number' ? fullStamp(new Date(label)) : String(label)}</p>
      {payload.filter((p) => p.dataKey !== 'iso').map((p) => (
        <p key={String(p.name)}>
          <span className="text-surface-700 dark:text-surface-300">{String(p.name)} </span>
          <span className="num">{typeof p.value === 'number' ? formatReading(p.value, unit, digits) : '-'}</span>
        </p>
      ))}
      {bucket && typeof payload[0]?.payload?.reading_count === 'number' && (
        <>
          <p className="text-surface-700 dark:text-surface-300">{bucketTooltip(String(payload[0].dataKey ?? ''), payload[0].payload.reading_count)}</p>
          {typeof label === 'number' && <p className="text-surface-700 dark:text-surface-300">Bucket of {bucketLabel(bucket)}s, {fullStamp(new Date(label))} to {fullStamp(new Date(label + bucket * 1000))}</p>}
        </>
      )}
    </div>
  );
}

interface Props {
  metric: ChartMetric;
  // rows in time order, each with its time `t`
  data: ChartRow[];
  // the span the chart covers: the window start to now, so a silence is drawn as wide as it was
  window: { start: number; end: number };
  // how often a row is expected, in milliseconds (the device's interval or the bucket width). Null when not known.
  intervalMs?: number | null;
  // what the field reads now, decided by currentReading. Left out, the headline is the newest value in the window.
  current?: CurrentReading;
  // the anomaly score chart draws each reading faintly, a rolling average solidly and the alert threshold dashed
  threshold?: number;
  wide?: boolean;
  // seconds: each row is one bucket (a mean or a maximum for the score) so the rolling average is not drawn
  bucket?: number | null;
  marks?: ChartMark[];
  // a sentence under the title, for example that the model could not be used
  notice?: string | null;
  // an extra class for the outer box, for example a column span
  className?: string;
}

// the data is long, so the table for screen readers holds about this many evenly spaced rows
const TABLE_ROWS = 24;
// a silent span is labelled inside its band only when the band is this wide
const BAND_LABEL_PX = 120;
// the most points a line is drawn with. One point per few pixels is all a screen shows.
const MAX_DRAWN = 240;

function sample<T>(rows: T[], count: number): T[] {
  if (rows.length <= count) return rows;
  const step = (rows.length - 1) / (count - 1);
  return Array.from({ length: count }, (_, i) => rows[Math.round(i * step)]);
}

// one sensor as a small chart with its own scale, drawn against real time. A gap is left open and marked with an outlined band
// that names it, a null leaves the line broken and the headline says "No reading" when the sensor cannot vouch for a value.
// Presentational: the container supplies rows. The chart is a picture with a text alternative and the same numbers and the
// same gaps sit in a table that only screen readers meet.
const NO_MARKS: ChartMark[] = [];

function ReadingChartView({ metric, data, window: win, intervalMs, current, threshold, wide, bucket, marks = NO_MARKS, notice, className = '' }: Props) {
  const key = metric.key;
  // the series arrays are worked out once for the rows given and not on every render
  const { numeric, values, times } = useMemo(() => {
    const numeric = data.filter((r) => typeof r[key] === 'number');
    return { numeric, values: numeric.map((r) => r[key] as number), times: numeric.map((r) => r.t) };
  }, [data, key]);
  const low = values.length ? Math.min(...values) : undefined;
  const high = values.length ? Math.max(...values) : undefined;
  const newest = values.length ? values[values.length - 1] : undefined;
  // the headline is what the field reads now. Without a decision from the container it is the newest value in the window.
  const shownValue = current ? (current.status === 'value' && typeof current.value === 'number' ? current.value : undefined) : newest;
  const alarming = threshold !== undefined && shownValue !== undefined && shownValue >= threshold;
  const fmt = (v: number) => formatReading(v, metric.unit, metric.digits);
  const isScore = threshold !== undefined;
  const bucketed = Boolean(bucket);
  const title = metric.unit ? `${metric.label}, ${metric.unit}` : metric.label;

  const gaps: Gap[] = useMemo(() => findGaps(times, win, gapThresholdMs(times, intervalMs ?? null)), [times, win, intervalMs]);
  // an isolated point (no neighbour on either side) cannot be drawn by a line, so it is a series of its own with a dot where it has a value
  // and nothing elsewhere. The main line then has no dot per point, which is what kept the chart's DOM small.
  const rows = useMemo(() => {
    // at most about 240 points are drawn however many there are: every peak and dip stays and the gaps are found from the full data
    const broken = decimateSeries(breakAtGaps(data, gaps) as ChartRow[], key, MAX_DRAWN);
    return broken.map((r, i) => {
      const alone = typeof r[key] === 'number' && typeof broken[i - 1]?.[key] !== 'number' && typeof broken[i + 1]?.[key] !== 'number';
      return alone ? { ...r, iso: r[key] as number } : r;
    });
  }, [data, gaps, key]);
  const longest = gaps.reduce((n, g) => Math.max(n, g.to - g.from), 0);

  const summary = (() => {
    const gapText = gaps.length === 0 ? '' : ` ${plural(gaps.length, 'gap')} with no readings, the longest ${spanWords(longest)}.`;
    if (current && current.status !== 'value') return `${metric.label}: no reading now, ${current.reason}.${gapText}`;
    if (shownValue === undefined || low === undefined || high === undefined) return `${metric.label}: no readings.${gapText}`;
    return `${metric.label} over the chosen range: latest ${fmt(shownValue)}, lowest ${fmt(low)}, highest ${fmt(high)}${threshold !== undefined ? `. The alert threshold is ${threshold.toFixed(2)}` : ''}.${gapText}`;
  })();

  // the ticks are chosen for the width the chart really has, so labels never repeat or run into each other on a phone
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => setWidth(el.clientWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const plotWidth = width - (isScore ? 40 : 64) - 8;
  const style = tickStyle(win.end - win.start);
  const ticks = useMemo(
    () => dedupeTicks(chooseTimeTicks(win.start, win.end, maxTicksFor(plotWidth, style === 'daytime' ? 12 : 5)), (t) => tickLabel(new Date(t).toISOString(), style)),
    [win, plotWidth, style],
  );
  const span = Math.max(1, win.end - win.start);

  // the text alternative: evenly spaced readings, every gap and the points marked
  const table = useMemo(() => {
    const entries: { t: number; label: string; text: string }[] = sample(numeric, TABLE_ROWS).map((r) => ({ t: r.t, label: fullStamp(new Date(r.t)), text: fmt(r[key] as number) }));
    for (const g of gaps) entries.push({ t: g.from, label: `${fullStamp(new Date(g.from))} to ${fullStamp(new Date(g.to))}`, text: `No readings for ${spanWords(g.to - g.from)}` });
    for (const m of marks) entries.push({ t: m.t, label: fullStamp(new Date(m.t)), text: m.text });
    return entries.sort((a, b) => a.t - b.t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [numeric, gaps, marks]);

  const legend = [
    { name: bucketed && bucket ? `Highest in each ${bucketLabel(bucket)} bucket` : 'Each reading', stroke: 'var(--chart-series)', width: isScore && !bucketed ? 1 : 2, dash: isScore && !bucketed ? '2 3' : undefined },
    ...(!bucketed && isScore && values.length >= 2 ? [{ name: '10-reading average', stroke: 'var(--chart-series)', width: 2.5, dash: undefined as string | undefined }] : []),
    ...(threshold !== undefined ? [{ name: `Alert threshold ${threshold.toFixed(2)}`, stroke: 'var(--chart-limit)', width: 1.5, dash: '6 4' as string | undefined }] : []),
  ];

  return (
    <div className={`min-w-0 ${className}`}>
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-base font-semibold text-surface-900 dark:text-surface-50">{title}</h3>
        <p className={`text-base font-semibold ${alarming ? 'text-critical-800 dark:text-critical-300' : 'text-surface-900 dark:text-surface-50'}`}>
          {shownValue === undefined ? <span className="font-normal text-surface-800 dark:text-surface-200">No reading</span> : <span className="num">{fmt(shownValue)}</span>}
          {alarming && <span className="ml-2 text-meta font-medium">Above threshold</span>}
        </p>
      </div>
      {current && current.status !== 'value' && (
        <p className="text-meta text-surface-700 dark:text-surface-300">
          {current.status === 'stale' ? `Last value ${current.lastValueAt ? fullStamp(new Date(current.lastValueAt)) : ''}: ${current.reason}.` : `${current.reason?.charAt(0).toUpperCase()}${current.reason?.slice(1)}.`}
        </p>
      )}
      {notice && <p className="text-meta font-medium text-surface-900 dark:text-surface-50">{notice}</p>}
      {(isScore || marks.length > 0 || gaps.length > 0) && (
        // the series are named in a legend row above the plot, each with a sample of its line, so no name is drawn over the axis and
        // no name relies on colour. The samples differ by weight and dash. A silent span has an outlined band with its own entry.
        <ul className="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-meta text-surface-800 dark:text-surface-200">
          {isScore && legend.map((l) => (
            <li key={l.name} className="flex items-center gap-2">
              <svg width="28" height="8" viewBox="0 0 28 8" aria-hidden="true" focusable="false" className="shrink-0">
                <line x1="1" y1="4" x2="27" y2="4" stroke={l.stroke} strokeWidth={l.width} strokeDasharray={l.dash} />
              </svg>
              {l.name}
            </li>
          ))}
          {gaps.length > 0 && (
            <li className="flex items-center gap-2">
              <svg width="28" height="12" viewBox="0 0 28 12" aria-hidden="true" focusable="false" className="shrink-0">
                <rect x="1" y="1" width="26" height="10" fill="var(--chart-grid)" fillOpacity="0.45" stroke="var(--chart-axis)" strokeDasharray="3 2" />
              </svg>
              No readings
            </li>
          )}
          {marks.some((m) => m.kind !== 'late') && (
            <li className="flex items-center gap-2">
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" focusable="false" className="shrink-0">
                <path d="M7 1 13 7 7 13 1 7Z" fill="var(--chart-limit)" stroke="var(--chart-axis)" />
              </svg>
              Beyond the sensor&apos;s range
            </li>
          )}
          {marks.some((m) => m.kind === 'late') && (
            <li className="flex items-center gap-2">
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" focusable="false" className="shrink-0">
                <rect x="2" y="2" width="10" height="10" fill="none" stroke="var(--chart-axis)" strokeWidth="2" />
              </svg>
              Arrived late, not judged
            </li>
          )}
        </ul>
      )}
      <div ref={box} role="img" aria-label={summary} className={`${wide ? 'h-44' : 'h-36'} mt-2`}>
        <ResponsiveContainer width="100%" height="100%">
          {/* the chart's own keyboard layer would add an unnamed tab stop: the summary above and the data table carry the content */}
          <LineChart data={rows} accessibilityLayer={false} margin={{ top: 16, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--chart-grid)" strokeWidth={1} strokeDasharray="0" />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={[win.start, win.end]}
              allowDataOverflow
              ticks={ticks}
              interval={0}
              stroke="var(--chart-grid)"
              tickLine={false}
              // a tick near an edge is anchored to that edge, so the text is never cut by the svg
              tick={(t: { x?: number | string; y?: number | string; payload?: { value?: unknown } }) => {
                const v = Number(t.payload?.value);
                const at = (v - win.start) / span;
                return (
                  <text x={Number(t.x)} y={Number(t.y)} dy={14} fontSize={13} fill="var(--chart-axis)" textAnchor={at > 0.94 ? 'end' : at < 0.06 ? 'start' : 'middle'}>
                    {tickLabel(new Date(v).toISOString(), style)}
                  </text>
                );
              }}
            />
            <YAxis
              tick={{ fontSize: 13, fill: 'var(--chart-axis)' }}
              axisLine={false}
              tickLine={false}
              width={isScore ? 40 : 64}
              tickCount={4}
              tickFormatter={(v: number) => (isScore ? String(Number(v.toFixed(2))) : formatReading(v, '', Math.abs(v) >= 100 ? 0 : Math.max(1, metric.digits)))}
              domain={isScore ? [0, 1] : ['auto', 'auto']}
            />
            <Tooltip isAnimationActive={false} cursor={{ stroke: 'var(--chart-axis)', strokeWidth: 1 }} content={(p) => <ChartTooltip {...(p as unknown as TipProps)} unit={metric.unit} digits={metric.digits} bucket={bucket} />} />
            {gaps.map((g) => (
              <ReferenceArea
                key={`${g.from}-${g.to}`}
                x1={g.from}
                x2={g.to}
                fill="var(--chart-grid)"
                fillOpacity={0.32}
                stroke="var(--chart-axis)"
                strokeDasharray="3 3"
                strokeOpacity={0.55}
                ifOverflow="hidden"
                label={((g.to - g.from) / span) * plotWidth >= BAND_LABEL_PX ? { value: `No readings, ${spanWords(g.to - g.from)}`, position: 'center', fontSize: 13, fill: 'var(--chart-axis)' } : undefined}
              />
            ))}
            {isScore && <ReferenceLine y={threshold} stroke="var(--chart-limit)" strokeDasharray="6 4" strokeWidth={1.5} />}
            <Line
              type="linear"
              dataKey={key}
              name={bucketed && bucket ? `Highest in each ${bucketLabel(bucket)} bucket` : isScore ? 'Each reading' : metric.label}
              stroke="var(--chart-series)"
              strokeWidth={isScore && !bucketed ? 1 : 2}
              strokeDasharray={isScore && !bucketed ? '2 3' : undefined}
              dot={false}
              activeDot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
            <Line type="linear" dataKey="iso" name="Single reading" stroke="none" dot={{ r: 3, fill: 'var(--chart-series)', stroke: 'var(--chart-series)' }} activeDot={false} legendType="none" connectNulls={false} isAnimationActive={false} />
            {isScore && !bucketed && values.length >= 2 && (
              <Line type="linear" dataKey="score_trend" name="10-reading average" stroke="var(--chart-series)" strokeWidth={2.5} dot={false} connectNulls={false} isAnimationActive={false} />
            )}
            {marks.map((m) => m.kind === 'late' ? (
              <ReferenceDot key={`late-${m.t}`} x={m.t} y={m.value} r={5} ifOverflow="visible" shape={(p: { cx?: number; cy?: number }) => <rect x={(p.cx ?? 0) - 4} y={(p.cy ?? 0) - 4} width={8} height={8} fill="none" stroke="var(--chart-axis)" strokeWidth={2} />} />
            ) : (
              <ReferenceDot key={m.t} x={m.t} y={m.value} r={5} fill="var(--chart-limit)" stroke="var(--chart-axis)" ifOverflow="visible" />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {/* the wrapper clips the table: a table given sr-only itself still grows to its content and widens the page */}
      <div className="sr-only">
        <table>
          <caption>{`Data for ${title}, ${plural(numeric.length, 'point')}${gaps.length ? `, with ${plural(gaps.length, 'gap')} of no readings` : ''}`}</caption>
          <thead>
            <tr>
              <th scope="col">Time</th>
              <th scope="col">{title}</th>
            </tr>
          </thead>
          <tbody>
            {table.map((r, i) => (
              <tr key={i}>
                <td>{r.label}</td>
                <td>{r.text}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// a chart is redrawn only when what it shows changed: the rows, the window, the headline decision or the marks. The container builds
// a new object for each of those on every poll, so they are compared by value.
function same(a: Props, b: Props): boolean {
  const ca = a.current;
  const cb = b.current;
  return (
    a.data === b.data &&
    a.metric.key === b.metric.key &&
    a.window.start === b.window.start &&
    a.window.end === b.window.end &&
    a.intervalMs === b.intervalMs &&
    a.threshold === b.threshold &&
    a.bucket === b.bucket &&
    a.wide === b.wide &&
    a.notice === b.notice &&
    a.className === b.className &&
    (a.marks ?? NO_MARKS).length === (b.marks ?? NO_MARKS).length &&
    (a.marks ?? NO_MARKS).every((m, i) => m.t === (b.marks ?? NO_MARKS)[i].t && m.value === (b.marks ?? NO_MARKS)[i].value) &&
    (ca === cb || (!!ca && !!cb && ca.status === cb.status && ca.value === cb.value && ca.reason === cb.reason && ca.lastValueAt === cb.lastValueAt))
  );
}

export default memo(ReadingChartView, same);
