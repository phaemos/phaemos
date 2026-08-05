'use client';

// I fetch devices alongside rules so the form can offer a device picker
// rather than requiring the user to type a raw UUID.

import { useState, useEffect, useCallback } from 'react';
import api from '../../lib/api';
import type { AlertRule, Device } from '../../types/index';
import ErrorToast from '../ui/ErrorToast';

const SEVERITY_COLOURS: Record<string, string> = {
  info: 'bg-primary-100 dark:bg-primary-500/20 text-primary-700 dark:text-primary-300',
  warning: 'bg-warning-50 dark:bg-warning-500/20 text-warning-600 dark:text-warning-300',
  critical: 'bg-critical-50 dark:bg-critical-500/20 text-critical-600 dark:text-critical-300',
};

const CONDITION_LABELS: Record<string, string> = {
  gt: '>',
  lt: '<',
  eq: '=',
};

interface EditState {
  threshold: string;
  severity: string;
  condition: string;
}

const inputClass = 'w-full rounded bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-800 px-2 py-1.5 text-xs text-surface-800 dark:text-surface-200 focus:outline-none';
const inlineInputClass = 'rounded bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-800 px-1 py-0.5 text-xs text-surface-800 dark:text-surface-200';

export default function AlertRulesPanel() {
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editState, setEditState] = useState<EditState>({ threshold: '', severity: 'warning', condition: 'gt' });
  const [showForm, setShowForm] = useState(false);

  const [newRule, setNewRule] = useState({
    device_id: '',
    metric: '',
    condition: 'gt',
    threshold: '',
    severity: 'warning',
  });

  const fetchRules = useCallback(async () => {
    try {
      const [rulesRes, devicesRes] = await Promise.all([
        api.get<AlertRule[]>('/alert-rules'),
        api.get<Device[]>('/devices'),
      ]);
      setRules(rulesRes.data);
      setDevices(devicesRes.data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load alert rules');
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetching on mount, the documented effect pattern
  // (react.dev/learn/synchronizing-with-effects#fetching-data).
  useEffect(() => { fetchRules(); }, [fetchRules]); // eslint-disable-line react-hooks/set-state-in-effect

  const deviceName = (id: string) => devices.find((d) => d.id === id)?.name ?? id.slice(0, 8) + '...';

  const handleDelete = async (id: string) => {
    try {
      await api.delete(`/alert-rules/${id}`);
      setRules((prev) => prev.filter((r) => r.id !== id));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    }
  };

  const handleEditSave = async (id: string) => {
    try {
      const res = await api.put<AlertRule>(`/alert-rules/${id}`, {
        threshold: parseFloat(editState.threshold),
        severity: editState.severity,
        condition: editState.condition,
      });
      setRules((prev) => prev.map((r) => (r.id === id ? res.data : r)));
      setEditing(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Update failed');
    }
  };

  const handleCreate = async () => {
    if (!newRule.device_id || !newRule.metric || !newRule.threshold) {
      setError('Device, metric and threshold are required.');
      return;
    }
    try {
      const res = await api.post<AlertRule>('/alert-rules', {
        ...newRule,
        threshold: parseFloat(newRule.threshold),
      });
      setRules((prev) => [res.data, ...prev]);
      setNewRule({ device_id: '', metric: '', condition: 'gt', threshold: '', severity: 'warning' });
      setShowForm(false);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Create failed');
    }
  };

  if (loading) {
    return <div className="text-surface-400 dark:text-surface-600 text-sm py-4">Loading alert rules...</div>;
  }

  return (
    <div className="space-y-4">
      {error && <ErrorToast message={error} onDismiss={() => setError(null)} />}

      <div className="flex items-centre justify-between">
        <h3 className="text-sm font-semibold text-surface-800 dark:text-surface-200 uppercase tracking-wider">
          Alert Rules ({rules.length})
        </h3>
        <button
          type="button"
          onClick={() => setShowForm((s) => !s)}
          className="bg-brand-600 hover:bg-brand-700 active:scale-95 text-white px-4 py-2 rounded-lg text-sm font-medium transition-all duration-150"
        >
          {showForm ? 'Cancel' : '+ New Rule'}
        </button>
      </div>

      {showForm && (
        <div className="rounded-lg border border-surface-200 dark:border-surface-800 bg-surface-50 dark:bg-surface-900/60 p-4 space-y-3">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <div>
              <label className="block text-xs text-surface-600 dark:text-surface-400 mb-1">Device</label>
              <select value={newRule.device_id} onChange={(e) => setNewRule((s) => ({ ...s, device_id: e.target.value }))} className={inputClass}>
                <option value="">Select device...</option>
                {devices.map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-surface-600 dark:text-surface-400 mb-1">Metric</label>
              <input type="text" placeholder="e.g. temperature" value={newRule.metric} onChange={(e) => setNewRule((s) => ({ ...s, metric: e.target.value }))} className={inputClass} />
            </div>
            <div>
              <label className="block text-xs text-surface-600 dark:text-surface-400 mb-1">Condition</label>
              <select value={newRule.condition} onChange={(e) => setNewRule((s) => ({ ...s, condition: e.target.value }))} className={inputClass}>
                <option value="gt">Greater than (&gt;)</option>
                <option value="lt">Less than (&lt;)</option>
                <option value="eq">Equal to (=)</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-surface-600 dark:text-surface-400 mb-1">Threshold</label>
              <input type="number" placeholder="80" value={newRule.threshold} onChange={(e) => setNewRule((s) => ({ ...s, threshold: e.target.value }))} className={inputClass} />
            </div>
            <div>
              <label className="block text-xs text-surface-600 dark:text-surface-400 mb-1">Severity</label>
              <select value={newRule.severity} onChange={(e) => setNewRule((s) => ({ ...s, severity: e.target.value }))} className={inputClass}>
                <option value="info">Info</option>
                <option value="warning">Warning</option>
                <option value="critical">Critical</option>
              </select>
            </div>
          </div>
          <button type="button" onClick={handleCreate} className="px-4 py-1.5 rounded text-xs font-medium bg-brand-600 hover:bg-brand-700 text-white transition-colours">
            Create Rule
          </button>
        </div>
      )}

      {rules.length === 0 ? (
        <p className="text-surface-400 dark:text-surface-600 text-sm">No alert rules configured.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-surface-200 dark:border-surface-800">
          <table className="w-full text-xs text-left">
            <thead className="bg-surface-100 dark:bg-surface-800/60 text-surface-600 dark:text-surface-400 uppercase tracking-wider">
              <tr>
                <th className="px-3 py-2">Device</th>
                <th className="px-3 py-2">Metric</th>
                <th className="px-3 py-2">Condition</th>
                <th className="px-3 py-2">Threshold</th>
                <th className="px-3 py-2">Severity</th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-100 dark:divide-surface-800">
              {rules.map((rule) => (
                <tr key={rule.id} className="hover:bg-surface-50 dark:hover:bg-white/5 transition-colours">
                  <td className="px-3 py-2 font-mono text-surface-600 dark:text-surface-200">{deviceName(rule.device_id)}</td>
                  <td className="px-3 py-2 text-surface-800 dark:text-surface-200">{rule.metric}</td>

                  {editing === rule.id ? (
                    <>
                      <td className="px-3 py-2">
                        <select title="Condition" value={editState.condition} onChange={(e) => setEditState((s) => ({ ...s, condition: e.target.value }))} className={inlineInputClass}>
                          <option value="gt">&gt;</option>
                          <option value="lt">&lt;</option>
                          <option value="eq">=</option>
                        </select>
                      </td>
                      <td className="px-3 py-2">
                        <input title="Threshold" type="number" value={editState.threshold} onChange={(e) => setEditState((s) => ({ ...s, threshold: e.target.value }))} className={`w-20 ${inlineInputClass}`} />
                      </td>
                      <td className="px-3 py-2">
                        <select title="Severity" value={editState.severity} onChange={(e) => setEditState((s) => ({ ...s, severity: e.target.value }))} className={inlineInputClass}>
                          <option value="info">Info</option>
                          <option value="warning">Warning</option>
                          <option value="critical">Critical</option>
                        </select>
                      </td>
                      <td className="px-3 py-2 flex gap-1">
                        <button type="button" onClick={() => handleEditSave(rule.id)} className="px-2 py-0.5 rounded bg-brand-600 hover:bg-brand-700 text-white text-xs">Save</button>
                        <button type="button" onClick={() => setEditing(null)} className="px-2 py-0.5 rounded bg-surface-200 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 text-surface-800 dark:text-surface-200 text-xs">Cancel</button>
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="px-3 py-2 text-surface-600 dark:text-surface-400">{CONDITION_LABELS[rule.condition] ?? rule.condition}</td>
                      <td className="px-3 py-2 text-surface-800 dark:text-surface-200 font-mono">{rule.threshold}</td>
                      <td className="px-3 py-2">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${SEVERITY_COLOURS[rule.severity] ?? ''}`}>{rule.severity}</span>
                      </td>
                      <td className="px-3 py-2 flex gap-1">
                        <button type="button" onClick={() => { setEditing(rule.id); setEditState({ threshold: String(rule.threshold), severity: rule.severity, condition: rule.condition }); }} className="px-2 py-0.5 rounded bg-surface-200 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 text-surface-800 dark:text-surface-200 text-xs">Edit</button>
                        <button type="button" onClick={() => handleDelete(rule.id)} className="px-2 py-0.5 rounded bg-critical-50 dark:bg-critical-600/20 hover:bg-critical-100 dark:hover:bg-critical-600/30 text-critical-600 dark:text-white text-xs">Delete</button>
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
