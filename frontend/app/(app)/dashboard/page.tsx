'use client';

import { Suspense, useCallback, useMemo, useState } from 'react';
import type { Device, Alert } from '@/types';
import TelemetryChart from '@/components/TelemetryChart';
import HealthSummary from '@/components/dashboard/HealthSummary';
import MaintenanceBanner from '@/components/dashboard/MaintenanceBanner';
import MachineGrid from '@/components/dashboard/MachineGrid';
import NeedsAttention from '@/components/dashboard/NeedsAttention';
import FirstRun from '@/components/dashboard/FirstRun';
import type { KeyReading } from '@/components/dashboard/keyReadings';
import InlineError from '@/components/dashboard/InlineError';
import { sortAlerts, uniqueById } from '@/lib/alertLife';
import PageHeader from '@/components/ui/PageHeader';
import ReadOnlyNote from '@/components/ui/ReadOnlyNote';
import { useRole } from '@/hooks/useRole';
import { canWrite as canWriteRole } from '@/lib/role';
import { useApiResource } from '@/hooks/useApiResource';
import { AlertsGapProvider } from '@/components/machines/AlertsGap';
import { alertsGap, mostRecentlyPosted } from '@/lib/machineState';
import Segmented from '@/components/ui/Segmented';
import { Select } from '@/components/ui/Input';
import { SkeletonRows } from '@/components/ui/Skeleton';
import { useUrlParam } from '@/hooks/useUrlParam';
import type { Range } from '@/lib/telemetryRange';

// the most machines one request asks for. The overview says so when a fleet reaches it.
const DEVICE_LIMIT = 200;
// the most alerts one request asks for. The API allows 500.
const ALERT_LIMIT = 500;

const NODE_TYPES = [
  { value: 'all', label: 'All nodes' },
  { value: 'esp32', label: 'ESP32' },
  { value: 'stm32', label: 'STM32' },
  { value: 'nano', label: 'Nano' },
  { value: 'pico_w', label: 'Pico W' },
] as const;
type NodeType = (typeof NODE_TYPES)[number]['value'];
const NODE_VALUES = NODE_TYPES.map((n) => n.value);
const RANGE_VALUES = ['1h', '6h', '24h', '7d'] as const;

// the time range and the node type live in the address, which a page can only read inside a Suspense boundary
export default function DashboardPage() {
  return (
    <Suspense fallback={<SkeletonRows rows={6} label="Loading the overview" />}>
      <Overview />
    </Suspense>
  );
}

function Overview() {
  const role = useRole();
  // until the role is known no write control is offered, so a viewer never sees one flash
  const canWrite = canWriteRole(role);
  const [selected, setSelected] = useState<string | null>(null);
  const [nodeType, setNodeType] = useUrlParam<NodeType>('node', 'all', NODE_VALUES);
  const [range, setRange] = useUrlParam<Range>('range', '1h', RANGE_VALUES);
  // once the person has picked a machine, no poll chooses one for them
  const [userPicked, setUserPicked] = useState(false);

  // devices and active alerts are two reads, each polled every 10 seconds, so a failing alerts read never blocks the machine
  // cards. Only telemetry gets the real-time WebSocket treatment. The devices route returns 20 by default, so the limit is
  // raised to show a whole fleet. The alerts route says in X-Total-Count how many there are beyond its limit.
  const devicesRes = useApiResource<Device[]>('/devices', { params: { limit: DEVICE_LIMIT }, what: 'The machines', intervalMs: 10_000 });
  const alertsRes = useApiResource<Alert[]>('/alerts', { params: { resolved: false, limit: ALERT_LIMIT }, what: 'The alerts', intervalMs: 10_000 });
  const devices = useMemo(() => devicesRes.data ?? [], [devicesRes.data]);
  const alerts = useMemo(() => alertsRes.data ?? [], [alertsRes.data]);
  const gap = alertsGap(alertsRes);
  const alertsFailed = alertsRes.error !== null;

  // open on the machine that posted most recently, so the live readings panel has readings to show. Only the first answer chooses and
  // setting state while rendering is the documented way to do that without an effect.
  if (selected === null && devicesRes.data && !userPicked) {
    const first = mostRecentlyPosted(devices)?.id ?? null;
    if (first) setSelected(first);
  }

  // the chart already loads the selected machine's readings, so its headline values are shown on that machine's panel
  const [keyReadings, setKeyReadings] = useState<{ id: string; readings: KeyReading[] } | null>(null);
  const handleKeyReadings = useCallback((readings: KeyReading[]) => {
    if (selected) setKeyReadings({ id: selected, readings });
  }, [selected]);

  // one row for each alert, critical first and then the most recently seen
  const ordered = useMemo(() => sortAlerts(uniqueById(alerts)), [alerts]);
  const deviceNames = useMemo(() => Object.fromEntries(devices.map((d) => [d.id, d.name])), [devices]);

  const activeNodeType = nodeType === 'all' ? undefined : nodeType;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Overview"
        actions={
          <>
            {/* five options do not fit a phone, so there the same choice is a labelled select */}
            <div className="w-full sm:hidden">
              <Select label="Node type" value={nodeType} onChange={(e) => setNodeType(e.target.value as NodeType)}>
                {NODE_TYPES.map((n) => <option key={n.value} value={n.value}>{n.label}</option>)}
              </Select>
            </div>
            <div className="hidden sm:block">
              <Segmented label="Node type" hideLabel options={NODE_TYPES} value={nodeType} onChange={setNodeType} />
            </div>
          </>
        }
      />

      {role === 'viewer' && <ReadOnlyNote>You can read everything on this page. Creating a ticket from an alert is for technicians and admins.</ReadOnlyNote>}

      <MaintenanceBanner />
      <AlertsGapProvider gap={gap}>
      <HealthSummary alerts={alerts} devices={devicesRes.data ? devices : undefined} alertsGap={gap} />

      {alertsFailed && <InlineError message={alerts.length > 0 ? 'Alerts could not be refreshed. This list may be out of date.' : 'Alerts could not be loaded, so an empty list here does not mean all is well.'} onRetry={alertsRes.retry} />}

      <NeedsAttention
        alerts={ordered}
        deviceNames={deviceNames}
        alertCount={alertsRes.total ?? alerts.length}
        loadedCount={alerts.length}
      />

      {/* a fleet with no machines gets the first-run steps in place of an empty grid. It needs an answer, not a failure,
          so a request that failed or has not come back never shows it. */}
      {devicesRes.data && devices.length === 0 && devicesRes.error === null ? (
        <FirstRun role={role} />
      ) : (
      <MachineGrid
        devices={devices}
        alerts={alerts}
        loading={devicesRes.loading && !devicesRes.data}
        failed={devicesRes.error !== null}
        onRetry={devicesRes.retry}
        truncatedAt={DEVICE_LIMIT}
        total={devicesRes.total}
        selectedId={selected}
        onSelect={(id) => { setSelected(id); setUserPicked(true); }}
        readings={keyReadings ? { [keyReadings.id]: keyReadings.readings } : undefined}
      />
      )}

      {/* TelemetryChart manages its own fetch - pass device id and optional node type filter. */}
      {selected && <TelemetryChart deviceId={selected} nodeType={activeNodeType} device={devices.find((d) => d.id === selected) ?? null} range={range} onRangeChange={setRange} onKeyReadings={handleKeyReadings} />}
      </AlertsGapProvider>
    </div>
  );
}
