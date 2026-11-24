// the idea of the product in one drawing: each reading gets an anomaly score from 0 to 1. Four in five readings in a window at
// 0.7 or more raise an alert. The rule is the backend's (see the FAQ on the anomaly model). The scores are drawn for the
// illustration. The caption says so: they are not data from any machine.
//
// the marks are SVG and every word is HTML placed over it by percentage, so the labels keep their real size (13 px and
// up) at every width and zoom instead of shrinking with the drawing. Colours come from the chart tokens in globals.css.
const SCORES = [0.31, 0.27, 0.34, 0.3, 0.26, 0.33, 0.36, 0.31, 0.29, 0.35, 0.32, 0.38, 0.41, 0.39, 0.47, 0.53, 0.6, 0.67, 0.74, 0.79, 0.83];
const THRESHOLD = 0.7;

const W = 400;
const H = 220;
const LEFT = 14;
const RIGHT = 386;
const TOP = 30;
const BOTTOM = 196;

const x = (i: number) => LEFT + (i * (RIGHT - LEFT)) / (SCORES.length - 1);
const y = (s: number) => BOTTOM - s * (BOTTOM - TOP);
const pct = (v: number, of: number) => `${(v / of) * 100}%`;

export default function ScoreDiagram() {
  const line = SCORES.map((s, i) => `${x(i).toFixed(1)},${y(s).toFixed(1)}`).join(' ');
  const last = SCORES.length - 1;

  return (
    <figure className="w-full max-w-[34rem]">
      <div
        role="img"
        aria-label="Illustration: anomaly scores stay between 0.26 and 0.41 for twelve readings, climb, then the last three readings score 0.74, 0.79 and 0.83, above the 0.7 line. The alert is raised once most of a window is above it."
        className="relative w-full"
        style={{ aspectRatio: `${W} / ${H}` }}
      >
        <svg viewBox={`0 0 ${W} ${H}`} className="absolute inset-0 h-full w-full" aria-hidden="true" focusable="false">
          {/* the 0 and 1 ends of the scale */}
          <line x1={LEFT} x2={RIGHT} y1={y(0)} y2={y(0)} stroke="var(--chart-grid)" strokeWidth="1" />
          <line x1={LEFT} x2={RIGHT} y1={y(1)} y2={y(1)} stroke="var(--chart-grid)" strokeWidth="1" />
          {/* the anomaly line, dashed so it reads apart from the gridlines without its colour */}
          <line x1={LEFT} x2={RIGHT} y1={y(THRESHOLD)} y2={y(THRESHOLD)} stroke="var(--chart-limit)" strokeWidth="1.5" strokeDasharray="6 5" />
          <polyline points={line} fill="none" stroke="var(--chart-series)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
          {SCORES.map((s, i) =>
            s >= THRESHOLD ? (
              // a reading over the line is a square, so the difference is a shape as well as a colour
              <rect key={i} x={x(i) - 5} y={y(s) - 5} width="10" height="10" fill="var(--chart-limit)" />
            ) : (
              <circle key={i} cx={x(i)} cy={y(s)} r="3.5" fill="var(--chart-series)" />
            ),
          )}
          {/* the alert: a ring around the reading that raises it */}
          <circle cx={x(last)} cy={y(SCORES[last])} r="11" fill="none" stroke="var(--chart-limit)" strokeWidth="2" />
        </svg>

        <span className="label absolute -translate-y-full pb-1 text-surface-700 dark:text-surface-300" style={{ left: pct(LEFT, W), top: pct(y(1), H) }}>
          Score 1
        </span>
        <span className="label absolute pt-1 text-surface-700 dark:text-surface-300" style={{ left: pct(LEFT, W), top: pct(y(0), H) }}>
          0
        </span>
        <span className="label absolute pb-1 text-surface-900 dark:text-surface-50" style={{ left: pct(LEFT, W), bottom: pct(H - y(THRESHOLD), H) }}>
          0.7 anomaly line
        </span>
        <span
          className="label absolute -translate-x-full whitespace-nowrap pr-4 text-right font-semibold text-surface-900 dark:text-surface-50"
          style={{ left: pct(x(last), W), top: pct(y(SCORES[last]) - 26, H) }}
        >
          Alert raised
        </span>
      </div>
      <figcaption className="mt-8 max-w-[52ch] text-base text-surface-700 dark:text-surface-300">
        Each mark is one reading&apos;s anomaly score. Circles are normal and squares score 0.7 or more. Most squares in a window raise an alert. An illustration, not live data.
      </figcaption>
    </figure>
  );
}
