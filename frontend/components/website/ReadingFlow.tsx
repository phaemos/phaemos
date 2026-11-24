// "How a reading travels": one diagram from sensor node to dashboard. Two drawings share the same facts: a wide one
// from 1024 px and a tall one below it, so no label is drawn smaller than 13 px at any width. Both are decorative: the
// ordered list under them carries every label and every format as real text.
//
// the visible links are separate lines. Each drawing also has one invisible path (reading-path and
// reading-path-tall) that runs the whole route from the first node to the dashboard, for a later dot to follow.

const BOX = 'fill-surface-0 stroke-surface-500 dark:fill-surface-900';
const TITLE = 'fill-surface-900 dark:fill-surface-50';
const SUB = 'fill-surface-600 dark:fill-surface-400';
const LINK = 'fill-none stroke-surface-600 dark:stroke-surface-400';
const SANS = { fontSize: 15, fontWeight: 600 } as const;
const SMALL = { fontSize: 13 } as const;
const SMALL_T = { fontSize: 14 } as const;
const MONO_T = { fontSize: 13, fontFamily: 'var(--typeface-mono), ui-monospace, monospace' } as const;
const MONO = { fontSize: 13, fontFamily: 'var(--typeface-mono), ui-monospace, monospace' } as const;

function Arrow({ id }: { id: string }) {
  return (
    <marker id={id} markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto" markerUnits="userSpaceOnUse">
      <path d="M0 0 L9 4.5 L0 9 z" fill="currentColor" />
    </marker>
  );
}

function Wide() {
  return (
    <svg viewBox="0 0 900 380" aria-hidden="true" focusable="false" className="hidden h-auto w-full text-surface-600 dark:text-surface-400 lg:block">
      <defs><Arrow id="flow-arrow-wide" /></defs>

      <path id="reading-path" d="M170 55 H360 V120 H660 H780 V300" fill="none" stroke="none" />

      {/* nodes */}
      <rect x="1" y="20" width="168" height="70" rx="8" className={BOX} />
      <text x="16" y="48" className={TITLE} style={SANS}>STM32 Black Pill</text>
      <text x="16" y="70" className={SUB} style={SMALL}>vibration, FFT</text>

      <rect x="1" y="150" width="168" height="70" rx="8" className={BOX} />
      <text x="16" y="178" className={TITLE} style={SANS}>Arduino Nano</text>
      <text x="16" y="200" className={SUB} style={SMALL}>air, light, moisture</text>

      <rect x="1" y="290" width="168" height="70" rx="8" className={BOX} />
      <text x="16" y="318" className={TITLE} style={SANS}>Pico 2W</text>
      <text x="16" y="340" className={SUB} style={SMALL}>air and light</text>

      <rect x="361" y="20" width="179" height="200" rx="8" className={BOX} />
      <text x="451" y="108" textAnchor="middle" className={TITLE} style={SANS}>ESP32 hub</text>
      <text x="451" y="130" textAnchor="middle" className={SUB} style={SMALL}>11 sensors</text>
      <text x="451" y="150" textAnchor="middle" className={SUB} style={SMALL}>merges STM32 and Nano</text>

      <rect x="661" y="40" width="238" height="160" rx="8" className={BOX} />
      <text x="680" y="76" className={TITLE} style={SANS}>FastAPI backend</text>
      <text x="680" y="100" className={SUB} style={SMALL}>scores with Isolation Forest</text>
      <text x="680" y="120" className={SUB} style={SMALL}>stores in PostgreSQL</text>
      <text x="680" y="140" className={SUB} style={SMALL}>checks alert rules</text>

      <rect x="661" y="300" width="238" height="70" rx="8" className={BOX} />
      <text x="680" y="328" className={TITLE} style={SANS}>Next.js dashboard</text>
      <text x="680" y="350" className={SUB} style={SMALL}>live readings and alerts</text>

      {/* links */}
      <path d="M170 55 H358" className={LINK} strokeWidth="1.5" markerEnd="url(#flow-arrow-wide)" />
      <text x="180" y="30" className={TITLE} style={SMALL}>UART, 115200 baud</text>
      <text x="180" y="47" className={SUB} style={MONO}>VIB line, every 1.28 s</text>

      <path d="M170 185 H358" className={LINK} strokeWidth="1.5" markerEnd="url(#flow-arrow-wide)" />
      <text x="180" y="160" className={TITLE} style={SMALL}>Serial, 9600 baud</text>
      <text x="180" y="177" className={SUB} style={MONO}>CSV line, every 2 s</text>

      <path d="M540 120 H658" className={LINK} strokeWidth="1.5" markerEnd="url(#flow-arrow-wide)" />
      <text x="548" y="90" className={TITLE} style={SMALL}>HTTP POST</text>
      <text x="548" y="108" className={SUB} style={MONO}>JSON body</text>
      <text x="548" y="142" className={SUB} style={SMALL}>every 5 s</text>

      <path d="M170 325 H570 V175 H658" className={LINK} strokeWidth="1.5" markerEnd="url(#flow-arrow-wide)" />
      <text x="182" y="313" className={TITLE} style={SMALL}>HTTP POST, JSON, every 5 s, over Wi-Fi</text>

      <path d="M780 200 V298" className={LINK} strokeWidth="1.5" markerEnd="url(#flow-arrow-wide)" />
      <text x="768" y="244" textAnchor="end" className={TITLE} style={SMALL}>WebSocket</text>
      <text x="768" y="262" textAnchor="end" className={SUB} style={MONO}>/ws/telemetry/{'{device_id}'}</text>
    </svg>
  );
}

function Tall() {
  return (
    <svg viewBox="0 0 340 680" aria-hidden="true" focusable="false" className="h-auto w-full max-w-[440px] text-surface-600 dark:text-surface-400 lg:hidden">
      <defs><Arrow id="flow-arrow-tall" /></defs>

      <path id="reading-path-tall" d="M40 28 V205 H170 V460 V640" fill="none" stroke="none" />

      <rect x="1" y="0" width="168" height="56" rx="8" className={BOX} />
      <text x="14" y="24" className={TITLE} style={SANS}>STM32 Black Pill</text>
      <text x="14" y="44" className={SUB} style={SMALL_T}>vibration, FFT</text>

      <rect x="181" y="0" width="158" height="56" rx="8" className={BOX} />
      <text x="194" y="24" className={TITLE} style={SANS}>Arduino Nano</text>
      <text x="194" y="44" className={SUB} style={SMALL_T}>air, light, moisture</text>

      <path d="M40 56 V168" className={LINK} strokeWidth="1.5" markerEnd="url(#flow-arrow-tall)" />
      <text x="52" y="92" className={TITLE} style={SMALL_T}>UART, 115200 baud</text>
      <text x="52" y="110" className={SUB} style={MONO_T}>VIB line</text>
      <text x="52" y="126" className={SUB} style={MONO_T}>every 1.28 s</text>

      <path d="M190 56 V168" className={LINK} strokeWidth="1.5" markerEnd="url(#flow-arrow-tall)" />
      <text x="202" y="92" className={TITLE} style={SMALL_T}>Serial, 9600 baud</text>
      <text x="202" y="110" className={SUB} style={MONO_T}>CSV line</text>
      <text x="202" y="126" className={SUB} style={MONO_T}>every 2 s</text>

      <rect x="1" y="170" width="338" height="70" rx="8" className={BOX} />
      <text x="14" y="198" className={TITLE} style={SANS}>ESP32 hub</text>
      <text x="14" y="220" className={SUB} style={SMALL_T}>11 sensors, merges STM32 and Nano</text>

      <path d="M60 240 V398" className={LINK} strokeWidth="1.5" markerEnd="url(#flow-arrow-tall)" />
      <text x="72" y="280" className={TITLE} style={SMALL_T}>HTTP POST</text>
      <text x="72" y="298" className={SUB} style={MONO_T}>JSON body</text>
      <text x="72" y="314" className={SUB} style={MONO_T}>every 5 s</text>

      <rect x="211" y="262" width="128" height="60" rx="8" className={BOX} />
      <text x="224" y="286" className={TITLE} style={SANS}>Pico 2W</text>
      <text x="224" y="306" className={SUB} style={SMALL_T}>air and light</text>

      <path d="M275 322 V398" className={LINK} strokeWidth="1.5" markerEnd="url(#flow-arrow-tall)" />
      <text x="263" y="344" textAnchor="end" className={TITLE} style={SMALL_T}>HTTP POST, JSON</text>
      <text x="263" y="362" textAnchor="end" className={SUB} style={MONO_T}>Wi-Fi, every 5 s</text>

      <rect x="1" y="400" width="338" height="120" rx="8" className={BOX} />
      <text x="14" y="432" className={TITLE} style={SANS}>FastAPI backend</text>
      <text x="14" y="458" className={SUB} style={SMALL_T}>scores with Isolation Forest</text>
      <text x="14" y="478" className={SUB} style={SMALL_T}>stores in PostgreSQL</text>
      <text x="14" y="498" className={SUB} style={SMALL_T}>checks alert rules</text>

      <path d="M170 520 V608" className={LINK} strokeWidth="1.5" markerEnd="url(#flow-arrow-tall)" />
      <text x="182" y="556" className={TITLE} style={SMALL_T}>WebSocket</text>
      <text x="182" y="574" className={SUB} style={MONO_T}>/ws/telemetry/</text>
      <text x="182" y="590" className={SUB} style={MONO_T}>{'{device_id}'}</text>

      <rect x="1" y="610" width="338" height="60" rx="8" className={BOX} />
      <text x="14" y="636" className={TITLE} style={SANS}>Next.js dashboard</text>
      <text x="14" y="656" className={SUB} style={SMALL_T}>live readings and alerts</text>
    </svg>
  );
}

const code = 'break-words rounded bg-surface-100 px-1 py-0.5 font-mono text-[max(0.8125rem,0.9em)] text-surface-900 [overflow-wrap:anywhere] dark:bg-surface-800 dark:text-surface-50';

export default function ReadingFlow() {
  return (
    <div>
      <div className="rounded-lg border border-surface-200 bg-surface-0 p-2 sm:p-4 dark:border-surface-800 dark:bg-surface-900 lg:p-6">
        <Wide />
        <Tall />
      </div>
      <ol className="mt-8 max-w-[72ch] list-decimal space-y-3 pl-6 text-surface-700 marker:text-surface-600 dark:text-surface-300 dark:marker:text-surface-400">
        <li>
          The STM32 Black Pill samples its vibration sensor at 100 Hz and sends one line per 1.28 second window over UART at 115200 baud, for example{' '}
          <code className={code}>VIB:0.02,-0.01,1.01,MAG:1.01,FFT_PEAK:12.5Hz</code>.
        </li>
        <li>
          The Arduino Nano sends one CSV line every 2 seconds over serial at 9600 baud, for example{' '}
          <code className={code}>TEMP:28.5,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0</code>.
        </li>
        <li>
          The ESP32 hub reads its own sensors and adds the two lines above. It posts one JSON body every 5 seconds to <code className={code}>/api/v1/telemetry</code> with
          its machine key in the <code className={code}>X-API-Key</code> header. The Pico 2W reads its own sensors and posts the same way over Wi-Fi.
        </li>
        <li>The backend scores each reading with an Isolation Forest from 0 to 1 and counts 0.7 or above as an anomaly. It stores the reading in PostgreSQL and checks the alert rules.</li>
        <li>
          The backend sends the stored reading as JSON over a WebSocket at <code className={code}>/ws/telemetry/{'{device_id}'}</code>. The dashboard draws it.
        </li>
      </ol>
    </div>
  );
}
