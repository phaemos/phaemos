'use client';

import { useEffect, useState } from 'react';
import type { Device } from '../../types/index';
import api from '../../lib/api';
import ErrorToast from '../ui/ErrorToast';

interface TicketFormProps {
  onSuccess?: () => void;
  prefill?: { device_id?: string; description?: string; title?: string };
}

export default function TicketForm({ onSuccess, prefill }: TicketFormProps) {
  const [title, setTitle] = useState(prefill?.title ?? '');
  const [description, setDescription] = useState(prefill?.description ?? '');
  const [priority, setPriority] = useState('');
  const [deviceId, setDeviceId] = useState(prefill?.device_id ?? '');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);

  // machines are picked by name; the form still sends the device id the API expects
  useEffect(() => {
    api.get<Device[]>('/devices').then((r) => setDevices(r.data)).catch(() => {});
  }, []);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!title.trim()) {
      setError('Title is required');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      // send only fields the user filled in - the backend treats omitted optional
      // fields as null so we do not need to strip them explicitly.
      await api.post('/tickets', {
        title,
        description: description || undefined,
        priority: priority || undefined,
        device_id: deviceId || undefined,
      });
      // reset form on success so the user can immediately create another ticket.
      setTitle('');
      setDescription('');
      setPriority('');
      setDeviceId('');
      onSuccess?.();
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to create ticket';
      setError(message);
    } finally {
      setSubmitting(false);
    }
  }

  const inputClass = 'w-full rounded-lg border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-800 px-3 py-2 text-sm text-surface-900 dark:text-surface-200 placeholder-surface-400 dark:placeholder-surface-600 focus:outline-none focus:ring-2 focus:ring-brand-500';
  const labelClass = 'block text-xs font-medium text-surface-600 dark:text-surface-400 mb-1';

  return (
    <>
      {error && <ErrorToast message={error} onDismiss={() => setError(null)} />}
      <form
        onSubmit={handleSubmit}
        className="grid gap-4 sm:grid-cols-2"
      >
        
        <div className="sm:col-span-2">
          <label htmlFor="ticket-title" className={labelClass}>Title</label>
          <input
            id="ticket-title"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Short description of the issue"
            className={inputClass}
            required
          />
        </div>

        <div className="sm:col-span-2">
          <label htmlFor="ticket-description" className={labelClass}>Description</label>
          <textarea
            id="ticket-description"
            rows={4}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Detailed explanation of the fault or maintenance required"
            className={`${inputClass} resize-none`}
          />
        </div>

        <div>
          <label htmlFor="ticket-priority" className={labelClass}>Priority</label>
          <select
            id="ticket-priority"
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            className={inputClass}
          >
            <option value="">Select priority</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
          </select>
        </div>

        <div>
          <label htmlFor="ticket-device-id" className={labelClass}>Machine</label>
          <select id="ticket-device-id" value={deviceId} onChange={(e) => setDeviceId(e.target.value)} className={inputClass}>
            <option value="">No specific machine</option>
            {devices.map((d) => (
              <option key={d.id} value={d.id}>{d.name}{d.location ? ` (${d.location})` : ''}</option>
            ))}
          </select>
        </div>
        <button
          type="submit"
          disabled={submitting}
          className="sm:col-span-2 justify-self-start rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 transition-colors focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? 'Creating…' : 'Create ticket'}
        </button>
      </form>
    </>
  );
}
