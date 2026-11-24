'use client';

// the machines are read alongside the rules so the form offers a picker rather than a raw id.

import { lookup } from '@/lib/lookup';
import { useMemo, useRef, useState } from 'react';
import api from '@/lib/api';
import { idempotent, newIdempotencyKey } from '@/lib/idempotency';
import { requestIdOf } from '@/lib/apiCode';
import RequestRef from '@/components/ui/RequestRef';
import type { AlertRule, Device } from '@/types';
import { useApiResource } from '@/hooks/useApiResource';
import { apiDetail } from '@/lib/apiDetail';
import { describeApiError } from '@/lib/apiError';
import { ALERT_METRICS, CONDITION_WORDS, metricLabel } from '@/lib/alertMetrics';
import Button from '@/components/ui/Button';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import DataTable from '@/components/ui/DataTable';
import EmptyState from '@/components/ui/EmptyState';
import ErrorNotice from '@/components/ui/ErrorNotice';
import { Input, Select } from '@/components/ui/Input';
import Panel from '@/components/ui/Panel';
import { SkeletonRows } from '@/components/ui/Skeleton';
import StatusBadge from '@/components/ui/StatusBadge';

const BLANK = { device_id: '', metric: '', condition: 'gt', threshold: '', severity: 'warning' };

export default function AlertRulesPanel() {
  const rules = useApiResource<AlertRule[]>('/alert-rules', { what: 'The alert rules' });
  const machines = useApiResource<Device[]>('/devices', { params: { limit: 200 }, what: 'The machines' });
  // the readings a rule may watch come from the API, the same list it checks a rule against. The local list is the fallback when the
  // read fails and a test keeps it from naming a field the backend does not have.
  const allowed = useApiResource<{ metrics: { key: string; type: string }[] }>('/alert-metrics', { what: 'The list of readings' });
  const metricOptions = useMemo(
    () => (allowed.data ? allowed.data.metrics.map((m) => ({ key: m.key, label: m.type === 'boolean' ? `${metricLabel(m.key)} (on or off)` : metricLabel(m.key) })) : ALERT_METRICS.map((m) => ({ key: m.key, label: m.label }))),
    [allowed.data],
  );
  const names = useMemo(() => Object.fromEntries((machines.data ?? []).map((d) => [d.id, d.name])), [machines.data]);

  // null is closed, 'new' is the create form and an id is the edit form for that rule
  const [formFor, setFormFor] = useState<string | 'new' | null>(null);
  const [values, setValues] = useState(BLANK);
  const [errors, setErrors] = useState<{ device_id?: string; metric?: string; threshold?: string }>({});
  const [formError, setFormError] = useState('');
  // one Idempotency-Key for this submission, kept across retries and dropped when the rule was made
  const submission = useRef<string | null>(null);
  const [formRef, setFormRef] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [toDelete, setToDelete] = useState<AlertRule | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  const set = (k: keyof typeof BLANK) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setValues((s) => ({ ...s, [k]: e.target.value }));

  function openNew() {
    setValues(BLANK);
    setErrors({});
    setFormError('');
    submission.current = null;
    setFormFor('new');
  }

  function openEdit(r: AlertRule) {
    setValues({ device_id: r.device_id, metric: r.metric, condition: r.condition, threshold: String(r.threshold), severity: r.severity });
    setErrors({});
    setFormError('');
    setFormFor(r.id);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setFormError('');
    const editing = formFor !== 'new';
    const next: typeof errors = {};
    if (!editing && !values.device_id) next.device_id = 'Choose a machine.';
    if (!editing && !values.metric) next.metric = 'Choose a reading.';
    if (values.threshold.trim() === '' || Number.isNaN(parseFloat(values.threshold))) next.threshold = 'Enter a number.';
    setErrors(next);
    if (Object.keys(next).length) return;

    setSaving(true);
    try {
      if (editing) {
        await api.patch<AlertRule>(`/alert-rules/${formFor}`, {
          threshold: parseFloat(values.threshold),
          severity: values.severity,
          condition: values.condition,
        });
      } else {
        await api.post<AlertRule>('/alert-rules', { ...values, threshold: parseFloat(values.threshold) }, idempotent((submission.current ??= newIdempotencyKey())));
        submission.current = null;
      }
      setFormFor(null);
      rules.retry();
    } catch (err) {
      setFormError(apiDetail(err) ?? describeApiError(err, 'The rule'));
      setFormRef(requestIdOf(err) ?? null);
    } finally {
      setSaving(false);
    }
  }

  async function confirmDelete() {
    if (!toDelete) return;
    setDeleting(true);
    setDeleteError('');
    try {
      await api.delete(`/alert-rules/${toDelete.id}`);
      setToDelete(null);
      rules.retry();
    } catch (err) {
      setDeleteError(describeApiError(err, 'The rule'));
    } finally {
      setDeleting(false);
    }
  }

  const rulesLoading = rules.loading && !rules.data;
  const machineList = machines.data ?? [];
  const editingRule = formFor && formFor !== 'new' ? rules.data?.find((r) => r.id === formFor) : null;

  return (
    <div className="space-y-6">
      {formFor && (
        <Panel title={formFor === 'new' ? 'New rule' : 'Edit rule'} description={editingRule ? `${lookup(names, editingRule.device_id) ?? 'Unknown machine'}, ${metricLabel(editingRule.metric)}. Only the condition, threshold and severity can change.` : 'A rule raises an alert when a reading crosses the threshold.'}>
          <form onSubmit={save} noValidate className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {formFor === 'new' && (
                <>
                  <Select label="Machine" required value={values.device_id} onChange={set('device_id')} error={errors.device_id} wrapperClassName="min-h-[100px]">
                    <option value="">Choose a machine</option>
                    {machineList.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                  </Select>
                  <Select label="Reading" required value={values.metric} onChange={set('metric')} error={errors.metric} wrapperClassName="min-h-[100px]">
                    <option value="">Choose a reading</option>
                    {metricOptions.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
                  </Select>
                </>
              )}
              <Select label="Condition" value={values.condition} onChange={set('condition')}>
                <option value="gt">Greater than</option>
                <option value="lt">Less than</option>
                <option value="eq">Equal to</option>
              </Select>
              <Input label="Threshold" required type="number" step="any" inputMode="decimal" value={values.threshold} onChange={set('threshold')} error={errors.threshold} wrapperClassName="min-h-[100px]" className="num" />
              <Select label="Severity" value={values.severity} onChange={set('severity')}>
                <option value="info">Info</option>
                <option value="warning">Warning</option>
                <option value="critical">Critical</option>
              </Select>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" pending={saving}>{formFor === 'new' ? 'Create rule' : 'Save rule'}</Button>
              <Button variant="secondary" onClick={() => setFormFor(null)}>Cancel</Button>
              <p role="alert" className="min-h-5 text-base font-medium text-critical-800 dark:text-critical-300">{formError}</p>
              {formError && <RequestRef id={formRef} />}
            </div>
          </form>
        </Panel>
      )}

      <Panel
        title="Rules"
        bodyClassName="p-0"
        actions={!formFor ? <Button onClick={openNew} disabled={machines.loading || !!machines.error}>New rule</Button> : undefined}
      >
        {rulesLoading ? (
          <div className="p-4"><SkeletonRows rows={4} label="Loading alert rules" /></div>
        ) : rules.error && !rules.data ? (
          <div className="p-4"><ErrorNotice message={rules.error} onRetry={rules.retry} /></div>
        ) : rules.data && rules.data.length === 0 ? (
          <EmptyState heading="No alert rules yet" subMessage="Add one to be told when a reading crosses a limit." />
        ) : rules.data ? (
          <>
            {(rules.error || machines.error) && <div className="p-4"><ErrorNotice message={rules.error ?? machines.error ?? ''} onRetry={rules.error ? rules.retry : machines.retry} /></div>}
            <DataTable caption="Alert rules">
              <thead>
                <tr>
                  <th scope="col">Machine</th>
                  <th scope="col">Reading</th>
                  <th scope="col">Condition</th>
                  <th scope="col" className="text-right">Threshold</th>
                  <th scope="col">Severity</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {rules.data.map((r) => (
                  <tr key={r.id}>
                    <td>{lookup(names, r.device_id) ?? <span className="text-surface-600 dark:text-surface-400">Unknown machine</span>}</td>
                    <td>{metricLabel(r.metric)}</td>
                    <td>{lookup(CONDITION_WORDS, r.condition) ?? r.condition}</td>
                    <td className="num">{r.threshold}</td>
                    <td><StatusBadge status={r.severity} /></td>
                    <td>
                      <div className="flex justify-end gap-2">
                        <Button size="small" variant="secondary" onClick={() => openEdit(r)} aria-label={`Edit the ${metricLabel(r.metric)} rule for ${lookup(names, r.device_id) ?? 'an unknown machine'}`}>Edit</Button>
                        <Button size="small" variant="secondary" onClick={() => { setDeleteError(''); setToDelete(r); }} aria-label={`Delete the ${metricLabel(r.metric)} rule for ${lookup(names, r.device_id) ?? 'an unknown machine'}`}>Delete</Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          </>
        ) : null}
      </Panel>

      <ConfirmDialog
        open={toDelete !== null}
        title="Delete this alert rule?"
        confirmLabel="Delete rule"
        onCancel={() => setToDelete(null)}
        onConfirm={confirmDelete}
        pending={deleting}
      >
        {toDelete && (
          <>
            <p>
              {metricLabel(toDelete.metric)} {(lookup(CONDITION_WORDS, toDelete.condition) ?? toDelete.condition).toLowerCase()} <span className="num">{toDelete.threshold}</span> on {lookup(names, toDelete.device_id) ?? 'an unknown machine'} will stop raising alerts. This cannot be undone.
            </p>
            <p role="alert" className="mt-2 min-h-5 font-medium text-critical-800 dark:text-critical-300">{deleteError}</p>
          </>
        )}
      </ConfirmDialog>
    </div>
  );
}
