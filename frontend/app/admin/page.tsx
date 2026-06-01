'use client';

import { useState } from 'react';
import api from '@/lib/api';
import UserTable from '@/components/admin/UserTable';
import AuditLog from '@/components/admin/AuditLog';
import AlertRulesPanel from '@/components/admin/AlertRulesPanel';

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
      <h1 className="text-2xl font-bold">Admin Panel</h1>

      {/* User management */}
      <section className="rounded-lg border border-gray-800 p-4 space-y-4">
        <h2 className="text-lg font-semibold">User Management</h2>
        <UserTable />
      </section>

      {/* Alert rules */}
      <section className="rounded-lg border border-gray-800 p-4 space-y-4">
        <h2 className="text-lg font-semibold">Alert Rules</h2>
        <AlertRulesPanel />
      </section>

      {/* OTA Firmware Upload */}
      <section className="rounded-lg border border-gray-800 p-4 space-y-4">
        <div>
          <h2 className="text-lg font-semibold">OTA Firmware Update</h2>
          <p className="text-gray-400 text-sm">
            Upload a compiled .bin file. Connected ESP32 devices will check for
            an update on next boot and flash automatically if the version is newer.
          </p>
        </div>

        <div className="space-y-3 max-w-md">
          <div>
            <label className="block text-sm text-gray-300 mb-1">Version string</label>
            <input
              type="text"
              placeholder="e.g. 1.1.0"
              value={fwVersion}
              onChange={(e) => setFwVersion(e.target.value)}
              className="w-full rounded bg-gray-900 border border-gray-700 px-3 py-2 text-sm focus:outline-none focus:border-gray-500"
            />
          </div>

          <div>
            <label htmlFor="fw-file" className="block text-sm text-gray-300 mb-1">
              Firmware file (.bin)
            </label>
            <input
              id="fw-file"
              type="file"
              accept=".bin"
              title="Select a compiled ESP32 .bin firmware file"
              onChange={(e) => setFwFile(e.target.files?.[0] ?? null)}
              className="w-full text-sm text-gray-400 file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:bg-gray-700 file:text-gray-200 hover:file:bg-gray-600"
            />
          </div>

          <button
            type="button"
            onClick={handleFirmwareUpload}
            disabled={uploading}
            className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-sm font-medium"
          >
            {uploading ? 'Uploading...' : 'Upload Firmware'}
          </button>

          {fwStatus && (
            <p className="text-sm text-gray-300">{fwStatus}</p>
          )}
        </div>
      </section>

      {/* Audit log */}
      <section className="rounded-lg border border-gray-800 p-4 space-y-4">
        <h2 className="text-lg font-semibold">Audit Log</h2>
        <AuditLog />
      </section>
    </main>
  );
}
