'use client';

import { useState, useEffect } from 'react';
import api from '../../lib/api';
import { useToast } from '../../hooks/useToast';

interface Webhook {
  id: string;
  name: string;
  url: string;
  enabled: boolean;
  template: string | null;
}

const inputClass =
  'w-full rounded bg-white dark:bg-surface-900 border border-surface-200 dark:border-surface-800 px-3 py-2 text-sm text-surface-900 dark:text-surface-50 focus:outline-none focus:border-primary-500';
const labelClass = 'block text-xs text-surface-500 dark:text-surface-400 mb-1';

export default function WebhooksPanel() {
  const { addToast } = useToast();
  const [webhooks, setWebhooks] = useState<Webhook[]>([]);
  const [loading, setLoading] = useState(true);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // New webhook form state
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [template, setTemplate] = useState('');
  const [saving, setSaving] = useState(false);

  async function load() {
    try {
      const { data } = await api.get<Webhook[]>('/webhooks');
      setWebhooks(data);
    } catch {
      addToast('error', 'Failed to load webhooks.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api.post('/webhooks', {
        name,
        url,
        enabled: true,
        template: template || null,
      });
      setName('');
      setUrl('');
      setTemplate('');
      setShowForm(false);
      addToast('success', 'Webhook created.');
      load();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        .response?.data?.detail ?? 'Failed to create webhook.';
      addToast('error', msg);
    } finally {
      setSaving(false);
    }
  }

  async function handleToggle(wh: Webhook) {
    try {
      await api.patch(`/webhooks/${wh.id}`, { enabled: !wh.enabled });
      setWebhooks(prev => prev.map(w => w.id === wh.id ? { ...w, enabled: !w.enabled } : w));
    } catch {
      addToast('error', 'Failed to update webhook.');
    }
  }

  async function handleTest(id: string) {
    setTestingId(id);
    try {
      const { data } = await api.post<{ success: boolean }>(`/webhooks/${id}/test`);
      addToast(data.success ? 'success' : 'error', data.success ? 'Test delivery succeeded.' : 'Test delivery failed - check the URL.');
    } catch {
      addToast('error', 'Test request failed.');
    } finally {
      setTestingId(null);
    }
  }

  async function handleDelete(id: string) {
    setDeletingId(id);
    try {
      await api.delete(`/webhooks/${id}`);
      setWebhooks(prev => prev.filter(w => w.id !== id));
      addToast('success', 'Webhook deleted.');
    } catch {
      addToast('error', 'Failed to delete webhook.');
    } finally {
      setDeletingId(null);
    }
  }

  if (loading) {
    return <div className="h-12 rounded-lg bg-surface-100 dark:bg-surface-800 animate-pulse" />;
  }

  return (
    <div className="space-y-4">
      {/* Webhook list */}
      {webhooks.length === 0 ? (
        <p className="text-sm text-surface-400">No webhooks configured.</p>
      ) : (
        <div className="divide-y divide-surface-100 dark:divide-surface-800 rounded-lg border border-surface-200 dark:border-surface-800 overflow-hidden">
          {webhooks.map(wh => (
            <div key={wh.id} className="flex items-start gap-3 px-4 py-3 bg-white dark:bg-surface-900">
              {/* Toggle */}
              <button
                type="button"
                onClick={() => handleToggle(wh)}
                title={wh.enabled ? 'Disable webhook' : 'Enable webhook'}
                className={[
                  'mt-0.5 w-9 h-5 rounded-full flex-shrink-0 transition-colors relative',
                  wh.enabled ? 'bg-success-500' : 'bg-surface-300 dark:bg-surface-600',
                ].join(' ')}
              >
                <span
                  className={[
                    'absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform',
                    wh.enabled ? 'translate-x-4' : 'translate-x-0.5',
                  ].join(' ')}
                />
              </button>

              {/* Details */}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-surface-800 dark:text-surface-200">{wh.name}</p>
                <p className="text-xs text-surface-400 truncate">{wh.url}</p>
                {wh.template && (
                  <p className="text-xs text-surface-500 mt-1 font-mono truncate">{wh.template}</p>
                )}
              </div>

              {/* Actions */}
              <div className="flex gap-2 flex-shrink-0">
                <button
                  type="button"
                  onClick={() => handleTest(wh.id)}
                  disabled={testingId === wh.id}
                  className="px-3 py-1 text-xs bg-primary-600 hover:bg-primary-500 disabled:opacity-50 text-white rounded-lg transition-colors"
                >
                  {testingId === wh.id ? 'Testing...' : 'Test'}
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(wh.id)}
                  disabled={deletingId === wh.id}
                  className="px-3 py-1 text-xs bg-critical-700 hover:bg-critical-600 disabled:opacity-50 text-white rounded-lg transition-colors"
                >
                  {deletingId === wh.id ? '...' : 'Delete'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Add webhook */}
      {showForm ? (
        <form onSubmit={handleCreate} className="space-y-3 rounded-lg border border-surface-200 dark:border-surface-800 p-4 bg-white dark:bg-surface-900">
          <h3 className="text-sm font-medium text-surface-700 dark:text-surface-300">New webhook</h3>
          <div>
            <label className={labelClass}>Name</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              required
              placeholder="e.g. Slack alerts"
              className={inputClass}
            />
          </div>
          <div>
            <label className={labelClass}>URL</label>
            <input
              type="url"
              value={url}
              onChange={e => setUrl(e.target.value)}
              required
              placeholder="https://hooks.slack.com/..."
              className={inputClass}
            />
          </div>
          <div>
            <label className={labelClass}>JSON template (optional)</label>
            <textarea
              value={template}
              onChange={e => setTemplate(e.target.value)}
              rows={3}
              placeholder='{"text": "{{message}}"}'
              className={inputClass + ' font-mono resize-none'}
            />
          </div>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-2 bg-primary-600 hover:bg-primary-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="px-4 py-2 bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 text-surface-700 dark:text-surface-300 rounded-lg text-sm font-medium transition-colors"
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <button
          type="button"
          onClick={() => setShowForm(true)}
          className="px-4 py-2 bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 text-surface-700 dark:text-surface-300 rounded-lg text-sm font-medium transition-colors"
        >
          + Add webhook
        </button>
      )}
    </div>
  );
}
