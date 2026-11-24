import { figure, parseEvidence, rangeMark, type RangeEvidence } from '@/lib/anomalyEvidence';
import { metricUnit } from '@/lib/alertGroups';

// a small mark of where a sensor's value sits against its usual range, on a track that always fits all three. The usual range is a thick
// bar, the value a diamond. Position carries the meaning: a diamond beyond the end of the bar is outside it and the words under the
// track say which side. Nothing depends on colour. The reading and the range are written out in the line above it, so the mark is hidden
// from assistive technology and only repeats them.
export default function RangeMark({ evidence }: { evidence: unknown }) {
  const s = parseEvidence(evidence)?.sensor;
  if (!s || s.kind !== 'range') return null;
  const r: RangeEvidence = s;
  const m = rangeMark(r);
  const unit = metricUnit(r.sensor);
  const u = unit ? (unit === '%' ? unit : ` ${unit}`) : '';
  const side = m.direction === 'inside' ? 'inside the usual range' : `${m.direction} the usual range`;
  return (
    <div aria-hidden="true" className="mt-2 max-w-md text-surface-800 dark:text-surface-200">
      <div className="relative h-6">
        {/* the track */}
        <span className="absolute inset-x-0 top-1/2 h-px bg-surface-500 dark:bg-surface-400" />
        {/* the usual range, a bar with an end stop on each side */}
        <span className="absolute top-1/2 h-2 -translate-y-1/2 border-x-2 border-surface-800 bg-surface-300 dark:border-surface-200 dark:bg-surface-600" style={{ left: `${m.low}%`, width: `${Math.max(m.high - m.low, 1)}%` }} />
        {/* where the value is: a diamond sitting on the track */}
        <svg width="14" height="14" viewBox="0 0 14 14" className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 text-critical-800 dark:text-critical-300 [&_path]:stroke-surface-0 dark:[&_path]:stroke-surface-900" style={{ left: `${m.value}%` }} focusable="false">
          <path d="M7 .75 13.25 7 7 13.25.75 7Z" fill="currentColor" strokeWidth="1" />
        </svg>
      </div>
      <p className="mt-0.5 flex flex-wrap justify-between gap-x-4 text-meta">
        <span>Usual <span className="num">{figure(r.low)} to {figure(r.high)}{u}</span></span>
        <span>Now <span className="num">{figure(r.value)}{u}</span>, {side}</span>
      </p>
    </div>
  );
}
