'use client';

import { useState } from 'react';
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

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!title.trim()) {
      setError('Title is required');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      // I send only fields the user filled in - the backend treats omitted optional
      // fields as null so we do not need to strip them explicitly.
      await api.post('/tickets', {
        title,
        description: description || undefined,
        priority: priority || undefined,
        device_id: deviceId || undefined,
      });
      // Reset form on success so the user can immediately create another ticket.
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

  const inputClass = 'w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-200 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500';
  const labelClass = 'block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1';

  return (
    <>
      {error && <ErrorToast message={error} onDismiss={() => setError(null)} />}
      <form
        onSubmit={handleSubmit}
        className="space-y-4 bg-gray-50 dark:bg-white/5 border border-gray-200 dark:border-gray-700 rounded-xl p-6"
      >
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-200">New Ticket</h2>

        <div>
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

        <div>
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
          <label htmlFor="ticket-device-id" className={labelClass}>Device ID</label>
          <input
            id="ticket-device-id"
            type="text"
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
            placeholder="UUID of the associated device (optional)"
            className={`${inputClass} font-mono`}
          />
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? 'Submitting...' : 'Submit Ticket'}
        </button>
      </form>
    </>
  );
}
