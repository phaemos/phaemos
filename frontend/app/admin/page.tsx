'use client';

import { useState } from 'react';
import api from '@/lib/api';
import UserTable from '@/components/admin/UserTable';
import AuditLog from '@/components/admin/AuditLog';
import AlertRulesPanel from '@/components/admin/AlertRulesPanel';
import WebhooksPanel from '@/components/admin/WebhooksPanel';
import MaintenanceWindowsPanel from '@/components/admin/MaintenanceWindowsPanel';

const sectionClass = 'rounded-lg border border-surface-200 dark:border-surface-800 p-4 space-y-4';
const inputClass = 'w-full rounded bg-white dark:bg-surface-900 border border-surface-200 dark:border-surface-800 px-3 py-2 text-sm text-surface-900 dark:text-surface-50 focus:outline-none focus:border-primary-500';
const labelClass = 'block text-sm text-surface-600 dark:text-surface-400 mb-1';

export default function AdminPage() {
  const [fwVersion, setFwVersion] = useState('');
  const [fwFile, setFwFile] = useState<File | null>(null);
  const [fwStatus, setFwStatus] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const handleFirmwareUpload = async () => {
    if (!fwFile || !fwVersion) {
      setFwStatus('Please enter a version and select a .bin file.');
      return;
    }
    if (!fwFile.name.endsWith('.bin')) {
      setFwStatus('Only .bin firmware files are accepted.');
      return;
    }

    setUploading(true);
    setFwStatus(null);

    // I use FormData to send the binary file as a multipart upload.
    const form = new FormData();
    form.append('file', fwFile);

    try {
      await api.post(`/firmware/upload?version=${encodeURIComponent(fwVersion)}`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setFwStatus(`Firmware v${fwVersion} uploaded. Devices will update on next boot.`);
      setFwVersion('');
      setFwFile(null);
    } catch {
      setFwStatus('Upload failed - check the console and server logs.');
    } finally {
      setUploading(false);
    }
  };

  return (
    <main className="p-6 max-w-5xl mx-auto space-y-8">
      <h1 className="text-2xl font-bold text-surface-900 dark:text-surface-50">Admin Panel</h1>

      <section className={sectionClass}>
        <h2 className="text-lg font-semibold text-surface-800 dark:text-surface-200">User Management</h2>
        <UserTable />
      </section>

      <section className={sectionClass}>
        <h2 className="text-lg font-semibold text-surface-800 dark:text-surface-200">Alert Rules</h2>
        <AlertRulesPanel />
      </section>

      <section className={sectionClass}>
        <div>
          <h2 className="text-lg font-semibold text-surface-800 dark:text-surface-200">OTA Firmware Update</h2>
          <p className="text-surface-600 dark:text-surface-400 text-sm mt-1">
            Upload a compiled .bin file. Connected ESP32 devices will check for
            an update on next boot and flash automatically if the version is newer.
          </p>
        </div>

        <div className="space-y-3 max-w-md">
          <div>
            <label className={labelClass}>Version string</label>
            <input
              type="text"
              placeholder="e.g. 1.1.0"
              value={fwVersion}
              onChange={(e) => setFwVersion(e.target.value)}
              className={inputClass}
            />
          </div>

          <div>
            <label htmlFor="fw-file" className={labelClass}>
              Firmware file (.bin)
            </label>
            <input
              id="fw-file"
              type="file"
              accept=".bin"
              title="Select a compiled ESP32 .bin firmware file"
              onChange={(e) => setFwFile(e.target.files?.[0] ?? null)}
              className="w-full text-sm text-surface-600 dark:text-surface-400 file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:bg-surface-200 dark:file:bg-surface-800 file:text-surface-800 dark:file:text-surface-200 hover:file:bg-surface-200 dark:hover:file:bg-surface-800"
            />
          </div>

          <button
            type="button"
            onClick={handleFirmwareUpload}
            disabled={uploading}
            className="bg-brand-600 hover:bg-brand-700 active:scale-95 text-white px-4 py-2 rounded-lg text-sm font-medium transition-all duration-150 disabled:opacity-50"
          >
            {uploading ? 'Uploading...' : 'Upload Firmware'}
          </button>

          {fwStatus && (
            <p className="text-sm text-surface-600 dark:text-surface-400">{fwStatus}</p>
          )}
        </div>
      </section>

      <section className={sectionClass}>
        <h2 className="text-lg font-semibold text-surface-800 dark:text-surface-200">Maintenance Windows</h2>
        <MaintenanceWindowsPanel />
      </section>

      <section className={sectionClass}>
        <h2 className="text-lg font-semibold text-surface-800 dark:text-surface-200">Webhooks</h2>
        <WebhooksPanel />
      </section>

      <section className={sectionClass}>
        <h2 className="text-lg font-semibold text-surface-800 dark:text-surface-200">Audit Log</h2>
        <AuditLog />
      </section>
    </main>
  );
}
