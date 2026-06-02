'use client';

import { useState } from 'react';
import api from '@/lib/api';
import UserTable from '@/components/admin/UserTable';
import AuditLog from '@/components/admin/AuditLog';
import AlertRulesPanel from '@/components/admin/AlertRulesPanel';

const sectionClass = 'rounded-lg border border-gray-200 dark:border-gray-800 p-4 space-y-4';
const inputClass = 'w-full rounded bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-700 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:border-blue-500';
const labelClass = 'block text-sm text-gray-600 dark:text-gray-300 mb-1';

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
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Admin Panel</h1>

      <section className={sectionClass}>
        <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-200">User Management</h2>
        <UserTable />
      </section>

      <section className={sectionClass}>
        <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-200">Alert Rules</h2>
        <AlertRulesPanel />
      </section>

      <section className={sectionClass}>
        <div>
          <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-200">OTA Firmware Update</h2>
          <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">
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
              className="w-full text-sm text-gray-500 dark:text-gray-400 file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:bg-gray-200 dark:file:bg-gray-700 file:text-gray-700 dark:file:text-gray-200 hover:file:bg-gray-300 dark:hover:file:bg-gray-600"
            />
          </div>

          <button
            type="button"
            onClick={handleFirmwareUpload}
            disabled={uploading}
            className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-sm font-medium text-white"
          >
            {uploading ? 'Uploading...' : 'Upload Firmware'}
          </button>

          {fwStatus && (
            <p className="text-sm text-gray-600 dark:text-gray-300">{fwStatus}</p>
          )}
        </div>
      </section>

      <section className={sectionClass}>
        <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-200">Audit Log</h2>
        <AuditLog />
      </section>
    </main>
  );
}
