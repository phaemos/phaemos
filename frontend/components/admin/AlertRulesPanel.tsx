'use client';

// I fetch devices alongside rules so the form can offer a device picker
// rather than requiring the user to type a raw UUID.

import { useState, useEffect, useCallback } from 'react';
import api from '../../lib/api';
import type { AlertRule, Device } from '../../types/index';
import ErrorToast from '../ui/ErrorToast';

const SEVERITY_COLOURS: Record<string, string> = {
  info:     'bg-blue-900/40 text-blue-300',
  warning:  'bg-yellow-900/40 text-yellow-300',
  critical: 'bg-red-900/40 text-red-300',
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

export default function AlertRulesPanel() {
  const [rules, setRules]       = useState<AlertRule[]>([]);
  const [devices, setDevices]   = useState<Device[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState<string | null>(null);
  const [editing, setEditing]   = useState<string | null>(null);
  const [editState, setEditState] = useState<EditState>({ threshold: '', severity: 'warning', condition: 'gt' });
  const [showForm, setShowForm] = useState(false);

  // New rule form state
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

  useEffect(() => { fetchRules(); }, [fetchRules]);

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
    return <div className="text-gray-500 text-sm py-4">Loading alert rules...</div>;
  }

  return (
    <div className="space-y-4">
      {error && <ErrorToast message={error} onDismiss={() => setError(null)} />}

      <div className="flex items-centre justify-between">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
          Alert Rules ({rules.length})
        </h3>
        <button
          type="button"
          onClick={() => setShowForm((s) => !s)}
          className="px-3 py-1 rounded text-xs font-medium bg-blue-700 hover:bg-blue-600 text-white transition-colours"
        >
          {showForm ? 'Cancel' : '+ New Rule'}
        </button>
      </div>

      {/* New rule form */}
      {showForm && (
        <div className="rounded-lg border border-gray-700 bg-gray-900/60 p-4 space-y-3">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Device</label>
              <select
                value={newRule.device_id}
                onChange={(e) => setNewRule((s) => ({ ...s, device_id: e.target.value }))}
                className="w-full rounded bg-gray-800 border border-gray-700 px-2 py-1.5 text-xs text-gray-200 focus:outline-none"
              >
                <option value="">Select device...</option>
                {devices.map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Metric</label>
              <input
                type="text"
                placeholder="e.g. temperature"
                value={newRule.metric}
                onChange={(e) => setNewRule((s) => ({ ...s, metric: e.target.value }))}
                className="w-full rounded bg-gray-800 border border-gray-700 px-2 py-1.5 text-xs text-gray-200 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Condition</label>
              <select
                value={newRule.condition}
                onChange={(e) => setNewRule((s) => ({ ...s, condition: e.target.value }))}
                className="w-full rounded bg-gray-800 border border-gray-700 px-2 py-1.5 text-xs text-gray-200 focus:outline-none"
              >
                <option value="gt">Greater than (&gt;)</option>
                <option value="lt">Less than (&lt;)</option>
                <option value="eq">Equal to (=)</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Threshold</label>
              <input
                type="number"
                placeholder="80"
                value={newRule.threshold}
                onChange={(e) => setNewRule((s) => ({ ...s, threshold: e.target.value }))}
                className="w-full rounded bg-gray-800 border border-gray-700 px-2 py-1.5 text-xs text-gray-200 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Severity</label>
              <select
                value={newRule.severity}
                onChange={(e) => setNewRule((s) => ({ ...s, severity: e.target.value }))}
                className="w-full rounded bg-gray-800 border border-gray-700 px-2 py-1.5 text-xs text-gray-200 focus:outline-none"
              >
                <option value="info">Info</option>
                <option value="warning">Warning</option>
                <option value="critical">Critical</option>
              </select>
            </div>
          </div>
          <button
            type="button"
            onClick={handleCreate}
            className="px-4 py-1.5 rounded text-xs font-medium bg-green-700 hover:bg-green-600 text-white transition-colours"
          >
            Create Rule
          </button>
        </div>
      )}

      {/* Rules table */}
      {rules.length === 0 ? (
        <p className="text-gray-500 text-sm">No alert rules configured.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-700">
          <table className="w-full text-xs text-left">
            <thead className="bg-gray-800/60 text-gray-400 uppercase tracking-wider">
              <tr>
                <th className="px-3 py-2">Device</th>
                <th className="px-3 py-2">Metric</th>
                <th className="px-3 py-2">Condition</th>
                <th className="px-3 py-2">Threshold</th>
                <th className="px-3 py-2">Severity</th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {rules.map((rule) => (
                <tr key={rule.id} className="hover:bg-white/5 transition-colours">
                  <td className="px-3 py-2 font-mono text-gray-300">{deviceName(rule.device_id)}</td>
                  <td className="px-3 py-2 text-gray-200">{rule.metric}</td>

                  {editing === rule.id ? (
                    <>
                      <td className="px-3 py-2">
                        <select
                          value={editState.condition}
                          onChange={(e) => setEditState((s) => ({ ...s, condition: e.target.value }))}
                          className="rounded bg-gray-800 border border-gray-600 px-1 py-0.5 text-xs text-gray-200"
                        >
                          <option value="gt">&gt;</option>
                          <option value="lt">&lt;</option>
                          <option value="eq">=</option>
                        </select>
                      </td>
                      <td className="px-3 py-2">
                        <input
                          type="number"
                          value={editState.threshold}
                          onChange={(e) => setEditState((s) => ({ ...s, threshold: e.target.value }))}
                          className="w-20 rounded bg-gray-800 border border-gray-600 px-1 py-0.5 text-xs text-gray-200"
                        />
                      </td>
                      <td className="px-3 py-2">
                        <select
                          value={editState.severity}
                          onChange={(e) => setEditState((s) => ({ ...s, severity: e.target.value }))}
                          className="rounded bg-gray-800 border border-gray-600 px-1 py-0.5 text-xs text-gray-200"
                        >
                          <option value="info">Info</option>
                          <option value="warning">Warning</option>
                          <option value="critical">Critical</option>
                        </select>
                      </td>
                      <td className="px-3 py-2 flex gap-1">
                        <button type="button" onClick={() => handleEditSave(rule.id)}
                          className="px-2 py-0.5 rounded bg-green-700 hover:bg-green-600 text-white text-xs">
                          Save
                        </button>
                        <button type="button" onClick={() => setEditing(null)}
                          className="px-2 py-0.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-200 text-xs">
                          Cancel
                        </button>
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="px-3 py-2 text-gray-400">
                        {CONDITION_LABELS[rule.condition] ?? rule.condition}
                      </td>
                      <td className="px-3 py-2 text-gray-200 font-mono">{rule.threshold}</td>
                      <td className="px-3 py-2">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${SEVERITY_COLOURS[rule.severity] ?? ''}`}>
                          {rule.severity}
                        </span>
                      </td>
                      <td className="px-3 py-2 flex gap-1">
                        <button type="button"
                          onClick={() => {
                            setEditing(rule.id);
                            setEditState({ threshold: String(rule.threshold), severity: rule.severity, condition: rule.condition });
                          }}
                          className="px-2 py-0.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-200 text-xs">
                          Edit
                        </button>
                        <button type="button" onClick={() => handleDelete(rule.id)}
                          className="px-2 py-0.5 rounded bg-red-800 hover:bg-red-700 text-white text-xs">
                          Delete
                        </button>
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
