import Panel from '@/components/ui/Panel';
import StatusBadge from '@/components/ui/StatusBadge';
import Time from '@/components/ui/Time';
import { formatCount, formatDateTime, plural } from '@/lib/format';
import { metricLabel } from '@/lib/alertMetrics';
import { durationWords, faultWords as faultWordsOf, faultSince, faultsOf, linkName, memoryWords, notAppliedSensors, resetReasonWords, sensorName, signalWords, supplyWords } from '@/lib/machineState';
import { serverNow } from '@/lib/serverClock';
import type { Device, Telemetry } from '@/types';
import type { ReactNode } from 'react';
import ReplaySection from './ReplaySection';

interface Props {
  device: Device;
  // the machine's newest readings, newest first, used to say how long a sensor has been in fault
  readings: readonly Telemetry[];
  // an admin's control for marking sensors as not fitted, shown at the end of the panel
  children?: ReactNode;
  // admins see the action for accepting a new counter and the claims the server did not act on
  isAdmin?: boolean;
  // called after a new counter was accepted, so the page reads the machine again
  onCounterAccepted?: () => void;
}

function Vital({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="label text-surface-700 dark:text-surface-300">{label}</dt>
      <dd className="mt-1 text-base text-surface-900 dark:text-surface-50">{children}</dd>
    </div>
  );
}

const sentence = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

// how long a fault has lasted, from the run of recent readings that carry it. A run that reaches the end of the rows only
// says "at least". Without a run the page says only that the node reported it.
function lastedWords(since: { at: string; atLeast: boolean } | null, reportedAt: string | null | undefined): string {
  if (!since) return reportedAt ? `reported ${formatDateTime(reportedAt)}` : 'for an unknown time';
  const seconds = (serverNow() - Date.parse(since.at)) / 1000;
  return since.atLeast ? `for at least ${durationWords(seconds)}` : `since ${formatDateTime(since.at)}`;
}

// how the machine is being watched: which sensors cannot be trusted and why, which alert rules are not being checked,
// how the links to other nodes are doing and how the node itself is doing. It says plainly when the node has never sent
// health information. Its id is the target of a link from a sensor alert.
export default function MonitoringHealth({ device, readings, children, isAdmin = false, onCounterAccepted }: Props) {
  const health = device.health;
  const faults = faultsOf(device);
  const rules = health?.rules_cannot_evaluate ?? [];
  const links = Object.entries(health?.links ?? {});
  const notApplied = isAdmin ? notAppliedSensors(readings) : [];

  const replay = <ReplaySection machineId={device.id} machineName={device.name ?? 'this machine'} device={device} isAdmin={isAdmin} onAccepted={() => onCounterAccepted?.()} />;
  // a node's claim of a fault that no alert backed is only shown to an admin, folded away: it changes nothing for the operator
  const claims = notApplied.length > 0 && (
    <details className="border-t border-surface-200 pt-2 dark:border-surface-800">
      <summary className="flex min-h-[44px] cursor-pointer items-center text-base font-semibold text-surface-900 dark:text-surface-50">Fault claims the server did not act on</summary>
      <p className="max-w-[72ch] text-base text-surface-800 dark:text-surface-200">
        The node said {notApplied.map((k) => sensorName(k)).join(', ')} {notApplied.length === 1 ? 'is' : 'are'} faulty in its latest post, but no sensor alert backs the claim. The values were kept and the alert rules judged them as normal. If the sensor really is faulty, check the node.
      </p>
    </details>
  );

  return (
    <Panel id="monitoring-health" title="Monitoring health" description="Whether the node's sensors can be trusted and how the node itself is doing. A sensor fault never raises a machine alert.">
      {!health && faults.length === 0 ? (
        <div className="space-y-6">
          <p className="max-w-[72ch] text-base text-surface-800 dark:text-surface-200">
            This node has not sent any health information. It may be running firmware from before health reporting or it has not posted since the machine was added.
          </p>
          {replay}
        </div>
      ) : (
        <div className="space-y-6">
          <section aria-labelledby="faults-title">
            <h3 id="faults-title" className="text-base font-semibold text-surface-900 dark:text-surface-50">Sensors</h3>
            {faults.length === 0 ? (
              <p className="mt-2 text-base text-surface-800 dark:text-surface-200">No faults reported.</p>
            ) : (
              <ul className="mt-2 divide-y divide-surface-200 border-y border-surface-200 dark:divide-surface-800 dark:border-surface-800">
                {faults.map((f) => {
                  const since = f.quiet ? null : faultSince(readings, f.key);
                  return (
                    <li key={f.key} className="py-3">
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                        <StatusBadge status={f.quiet ? 'unknown' : 'warning'} label={f.label} />
                        <span className="text-base text-surface-900 dark:text-surface-50">{sentence(f.name)}</span>
                        {f.state === 'unknown' || f.label === 'Unknown state' ? <span className="text-sm text-surface-700 dark:text-surface-300">{f.words}</span> : null}
                        {!f.quiet && <span className="text-sm text-surface-700 dark:text-surface-300">{f.source === 'server' ? 'in the latest post' : lastedWords(since, health?.reported_at)}</span>}
                        {f.state === 'not_fitted' && <span className="text-sm text-surface-700 dark:text-surface-300">Not expected on this machine, so it never makes the machine unknown.</span>}
                      </div>
                      {!f.quiet && (
                        <p className="mt-1 max-w-[72ch] text-sm text-surface-800 dark:text-surface-200">
                          {f.source === 'server' ? 'Found by the server from the readings, not reported by the node. ' : f.source === 'both' ? 'Reported by the node and seen by the server. ' : ''}
                          {f.serverState ? `The server sees it as ${faultWordsOf(f.serverState)}. ` : ''}
                          {f.advice ? <><span className="font-medium">What to check:</span> {f.advice}</> : null}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          {rules.length > 0 && (
            <section aria-labelledby="rules-title">
              <h3 id="rules-title" className="text-base font-semibold text-surface-900 dark:text-surface-50">Alert rules not being checked</h3>
              <p className="mt-1 max-w-[72ch] text-base text-surface-800 dark:text-surface-200">
                {plural(rules.length, 'rule')} cannot raise an alert right now, because the sensor that measures it is not working. No alert from {rules.length === 1 ? 'this rule' : 'these rules'} does not mean all is well.
              </p>
              <ul className="mt-2 divide-y divide-surface-200 border-y border-surface-200 dark:divide-surface-800 dark:border-surface-800">
                {rules.map((r) => (
                  <li key={r.rule_id} className="py-3 text-base text-surface-900 dark:text-surface-50">
                    <span className="font-medium">{metricLabel(r.metric)}</span>
                    <span className="text-surface-800 dark:text-surface-200">
                      {': '}
                      {r.sensor_key ? `${sensorName(r.sensor_key)} ` : 'the sensor '}
                      {r.state === 'not_fitted' ? 'is marked as not fitted' : 'is not trusted'}
                    </span>
                    {!r.sensor_key && <span className="block text-sm text-surface-700 dark:text-surface-300">{r.reason}</span>}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {links.length > 0 && (
            <section aria-labelledby="links-title">
              <h3 id="links-title" className="text-base font-semibold text-surface-900 dark:text-surface-50">Links to other nodes</h3>
              <p className="mt-1 max-w-[72ch] text-sm text-surface-700 dark:text-surface-300">Counted since the hub last started.</p>
              <div className="mt-2 space-y-4">
                {links.map(([key, l]) => {
                  const linkKey = `${key}_link`;
                  const notFitted = (device.not_fitted ?? []).includes(linkKey);
                  const silent = [l.ok, l.crc, l.gaps, l.restarts, l.up].every((v) => !v);
                  return (
                    <div key={key}>
                      <h4 className="text-base font-medium text-surface-900 dark:text-surface-50">{linkName(key)}</h4>
                      {notFitted ? (
                        <p className="mt-1 text-base text-surface-800 dark:text-surface-200">Not fitted</p>
                      ) : silent ? (
                        <p className="mt-1 text-base text-surface-800 dark:text-surface-200">No line received since the hub started</p>
                      ) : (
                        <dl className="mt-2 grid grid-cols-[minmax(0,1fr)] gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
                          <Vital label="Good lines">{typeof l.ok === 'number' ? <span className="tnum">{formatCount(l.ok)}</span> : 'Not reported'}</Vital>
                          <Vital label="Corrupt lines">{typeof l.crc === 'number' ? <span className="tnum">{formatCount(l.crc)}</span> : 'Not reported'}</Vital>
                          <Vital label="Lost lines">{typeof l.gaps === 'number' ? <span className="tnum">{formatCount(l.gaps)}</span> : 'Not reported'}</Vital>
                          <Vital label="Restarts of that node">{typeof l.restarts === 'number' ? <span className="tnum">{formatCount(l.restarts)}</span> : 'Not reported'}</Vital>
                          <Vital label="Uptime of that node">{typeof l.up === 'number' ? <span className="tnum">{durationWords(l.up)}</span> : 'Not reported'}</Vital>
                          {key === 'nano' && <Vital label="Nano supply voltage">{typeof l.vcc === 'number' ? <span className="tnum">{supplyWords(l.vcc)}</span> : 'Not reported'}</Vital>}
                        </dl>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {health?.diag && Object.keys(health.diag).length > 0 && (
            <details className="border-t border-surface-200 pt-2 dark:border-surface-800">
              <summary className="flex min-h-[44px] cursor-pointer items-center text-base font-semibold text-surface-900 dark:text-surface-50">Diagnostics</summary>
              <p className="max-w-[72ch] text-sm text-surface-700 dark:text-surface-300">What the node reported for bench work. The labels are the node&apos;s own counter names written out as words.</p>
              <dl className="mt-2 grid grid-cols-[minmax(0,1fr)] gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(health.diag).map(([k, v]) => (
                  <Vital key={k} label={k.replace(/_/g, ' ').replace(/([a-z0-9])([A-Z])/g, '$1 $2').toLowerCase()}>
                    <span className="tnum break-words">{typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v)}</span>
                  </Vital>
                ))}
              </dl>
            </details>
          )}

          {replay}

          {claims}

          {health && (
            <section aria-labelledby="vitals-title">
              <h3 id="vitals-title" className="text-base font-semibold text-surface-900 dark:text-surface-50">Node</h3>
              {health.board_mismatch && (
                <p role="status" className="mt-2 text-base font-medium text-surface-900 dark:text-surface-50">
                  <StatusBadge status="warning" label="Wrong board" /> The firmware image on this node does not match its board.
                </p>
              )}
              {health.reset_loop && (
                <p role="status" className="mt-2 text-base font-medium text-surface-900 dark:text-surface-50">
                  <StatusBadge status="warning" label="Restarting repeatedly" /> The node has restarted three times in ten minutes.
                </p>
              )}
              <dl className="mt-3 grid grid-cols-[minmax(0,1fr)] gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
                <Vital label="Firmware">{health.firmware_version ?? device.firmware_version ?? 'Not reported'}</Vital>
                <Vital label="Uptime">{typeof health.uptime_s === 'number' ? durationWords(health.uptime_s) : 'Not reported'}</Vital>
                <Vital label="Restarts">
                  {typeof health.boot_count === 'number' ? <span className="tnum">{formatCount(health.boot_count)}</span> : 'Not reported'}
                  {health.reset_reason && <span className="block text-sm text-surface-700 dark:text-surface-300">Last restart: {resetReasonWords(health.reset_reason)}</span>}
                </Vital>
                <Vital label="Signal strength">
                  {typeof health.rssi === 'number' ? <><span className="tnum">{health.rssi}&nbsp;dBm</span>, {signalWords(health.rssi)}</> : 'Not reported'}
                </Vital>
                <Vital label="Free memory">{typeof health.heap_free === 'number' ? <span className="tnum">{memoryWords(health.heap_free)}</span> : 'Not reported'}</Vital>
                <Vital label="Lost readings">
                  {typeof health.lost_posts === 'number' ? <span className="tnum">{formatCount(health.lost_posts)}</span> : 'Not reported'}
                  {health.last_gap_at && <span className="block text-sm text-surface-700 dark:text-surface-300">Last gap <Time value={health.last_gap_at} format="datetime" /></span>}
                </Vital>
              </dl>
              {health.reported_at && (
                <p className="mt-4 text-sm text-surface-700 dark:text-surface-300">
                  Health last reported <Time value={health.reported_at} format="relative" showExact />.
                </p>
              )}
            </section>
          )}
        </div>
      )}
      {children}
    </Panel>
  );
}
