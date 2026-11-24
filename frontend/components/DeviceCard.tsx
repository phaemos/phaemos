import type { Device } from '@/types';
import MachineStatus, { LastPost } from '@/components/machines/MachineStatus';
import { faultedFields, type AlertLike } from '@/lib/machineState';
import type { KeyReading } from '@/components/dashboard/keyReadings';

interface Props {
  device: Device;
  active: boolean;
  // left out, the card is a plain block with nothing to press
  onClick?: () => void;
  // the machine's active alerts, so its state can say Warning or Fault
  alerts?: readonly AlertLike[];
  // the latest two or three headline readings, when the page has them
  readings?: KeyReading[];
  // a fixed clock for sample data
  now?: number;
}

const NODE_LABELS: Record<string, string> = {
  esp32: 'ESP32 hub',
  stm32: 'STM32 vibration node',
  nano: 'Arduino Nano node',
  pico_w: 'Pico 2 W ambient node',
};

// one machine as a panel: name and location, what the machine is and how it is watched (each a shape and a word), node
// type, last seen and key readings
export default function DeviceCard({ device, active, onClick, readings, alerts, now }: Props) {
  // a sensor the node cannot vouch for shows no value: the newest one held would look current
  const faulted = faultedFields(device);
  const border = active
    ? 'border-brand-700 ring-1 ring-brand-700 dark:border-brand-400 dark:ring-brand-400'
    : 'border-surface-200 dark:border-surface-800';
  const hover = onClick ? 'hover:border-surface-500 dark:hover:border-surface-500' : '';
  const classes = `flex w-full flex-col items-stretch justify-start rounded-lg border bg-surface-0 p-4 text-left dark:bg-surface-900 ${border} ${hover}`;

  const body = (
    <>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-surface-900 dark:text-surface-50">{device.name}</p>
          <p className="mt-0.5 truncate text-meta text-surface-600 dark:text-surface-400">{device.location ?? 'No location'}</p>
        </div>
        {active && onClick && <p className="label shrink-0 text-brand-800 dark:text-brand-400">On chart</p>}
      </div>
      <div className="mt-2"><MachineStatus device={device} alerts={alerts} now={now} /></div>

      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-t border-surface-200 pt-3 text-meta dark:border-surface-800">
        <dt className="text-surface-600 dark:text-surface-400">Node</dt>
        <dd className="text-surface-800 dark:text-surface-200">{NODE_LABELS[device.type ?? ''] ?? device.type ?? 'Unknown node'}</dd>
        <dt className="text-surface-600 dark:text-surface-400">Last post</dt>
        <dd className="text-surface-800 dark:text-surface-200">
          <LastPost device={device} now={now} />
        </dd>
      </dl>

      {readings && readings.length > 0 && (
        <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-2 border-t border-surface-200 pt-3 dark:border-surface-800">
          {readings.map((r) => (
            <div key={r.label}>
              <dt className="text-meta text-surface-600 dark:text-surface-400">{r.label}</dt>
              <dd className="num text-sm font-semibold text-surface-900 dark:text-surface-50">
                {faulted.has(r.key) || r.noReading ? (
                  <span className="font-sans font-normal text-surface-800 dark:text-surface-200" title={r.noReading}>No reading</span>
                ) : (
                  <>
                    {r.value}
                    <span className="text-meta font-normal text-surface-600 dark:text-surface-400">{r.unit ? (r.unit === '%' ? '%' : `\u00a0${r.unit}`) : ''}</span>
                  </>
                )}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {device.tags && device.tags.length > 0 && (
        <p className="mt-3 text-meta text-surface-600 dark:text-surface-400">{device.tags.join(', ')}</p>
      )}
    </>
  );

  if (!onClick) return <div className={classes}>{body}</div>;
  return (
    <button type="button" onClick={onClick} aria-pressed={active} className={classes}>
      {body}
    </button>
  );
}
