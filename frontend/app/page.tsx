'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import type { Device, Alert } from '@/types';
import DeviceCard from '@/components/DeviceCard';
import AlertBanner from '@/components/AlertBanner';
import TelemetryChart from '@/components/TelemetryChart';
import HealthSummary from '@/components/dashboard/HealthSummary';
import MaintenanceBanner from '@/components/dashboard/MaintenanceBanner';
import Card from '@/components/ui/Card';
import PageHeader from '@/components/ui/PageHeader';
import Segmented from '@/components/ui/Segmented';

const NODE_TYPES = [
  { value: 'all', label: 'All nodes' },
  { value: 'esp32', label: 'ESP32' },
  { value: 'stm32', label: 'STM32' },
  { value: 'nano', label: 'Nano' },
  { value: 'pico_w', label: 'Pico W' },
] as const;
type NodeType = (typeof NODE_TYPES)[number]['value'];

export default function DashboardPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [nodeType, setNodeType] = useState<NodeType>('all');
  // track whether the user has manually picked a device so polling never
  // auto-selects the first device and overrides their choice.
  const [userSelected, setUserSelected] = useState(false);

  // poll devices and active alerts every 5 seconds - they change infrequently
  // so polling is fine. Only telemetry gets the real-time WebSocket treatment.
  useEffect(() => {
    const load = async () => {
      // use allSettled so a failing alerts query never blocks device cards from rendering.
      const [devResult, alertResult] = await Promise.allSettled([
        api.get<Device[]>('/devices'),
        api.get<Alert[]>('/alerts?resolved=false'),
      ]);
      if (devResult.status === 'fulfilled') {
        setDevices(devResult.value.data);
        // only auto-select the first device on the very first load, never on
        // subsequent polls - otherwise the selection resets every 5 seconds.
        // open on the machine that most needs attention: the one with the newest active alert
        const alerting = alertResult.status === 'fulfilled' ? alertResult.value.data[0]?.device_id : undefined;
        setSelected((prev) => {
          if (prev || userSelected) return prev;
          return alerting ?? devResult.value.data[0]?.id ?? null;
        });
      }
      if (alertResult.status === 'fulfilled') {
        setAlerts(alertResult.value.data);
      }
    };
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [userSelected]);

  const activeNodeType = nodeType === 'all' ? undefined : nodeType;

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <PageHeader
        title="Overview"
        description="Every machine's health, live readings and what needs attention now."
        actions={<Segmented label="Node type" options={NODE_TYPES} value={nodeType} onChange={setNodeType} />}
      />

      <MaintenanceBanner />
      <HealthSummary />

      {alerts.length > 0 && (
        <Card
          title="Needs attention"
          description={`${alerts.length} active ${alerts.length === 1 ? 'alert' : 'alerts'}`}
          bodyClassName="divide-y divide-surface-200 dark:divide-surface-800"
        >
          {alerts.slice(0, 5).map((a) => (
            <AlertBanner key={a.id} alert={a} />
          ))}
        </Card>
      )}

      <section aria-labelledby="machines-title" className="space-y-3">
        <h2 id="machines-title" className="text-sm font-semibold text-surface-900 dark:text-surface-50">Machines</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {devices.map((d) => (
            <DeviceCard
              key={d.id}
              device={d}
              active={selected === d.id}
              onClick={() => { setSelected(d.id); setUserSelected(true); }}
            />
          ))}
        </div>
      </section>

      {/* TelemetryChart manages its own fetch - pass device id and optional node type filter. */}
      {selected && <TelemetryChart deviceId={selected} nodeType={activeNodeType} />}
    </main>
  );
}
