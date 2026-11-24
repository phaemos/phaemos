'use client';

import { useState } from 'react';
import api from '@/lib/api';
import { describeApiError } from '@/lib/apiError';
import Button from '@/components/ui/Button';
import { useToast } from '@/hooks/useToast';
import { EXPORT_HOURS, exportFileName, exportFromTs } from '@/lib/exportFile';

// GET /telemetry/export needs the bearer header, which a plain link cannot send. So the file is fetched through
// lib/api.ts (token and refresh included) and handed to the browser as a blob behind a temporary link;
// the route takes device_id, from and to (from_ts and to_ts are the older names), has no row limit and returns the rows oldest first.
// the page shows the error (onError) where there is room for a notice, not inside the header's action row
export default function ExportCsvButton({ deviceId, name, onError }: { deviceId: string; name: string; onError: (message: string | null) => void }) {
  const { addToast } = useToast();
  const [pending, setPending] = useState(false);

  async function run() {
    setPending(true);
    onError(null);
    try {
      const now = new Date();
      const res = await api.get<Blob>('/telemetry/export', {
        params: { device_id: deviceId, from: exportFromTs(now) },
        responseType: 'blob',
      });
      const blob = res.data;
      // with no rows in the window the API still sends a header line, so say that and do not save a file of headers only
      const head = await blob.slice(0, 8192).text();
      const firstBreak = head.indexOf('\n');
      if (firstBreak !== -1 && blob.size <= firstBreak + 1) {
        addToast('info', `${name} sent no readings in the last ${EXPORT_HOURS} hours, so nothing was saved.`);
        return;
      }
      const file = exportFileName(name, now);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = file;
      document.body.appendChild(a);
      a.click();
      a.remove();
      // the click has handed the blob to the browser, so the temporary link can go
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
      addToast('success', `Saved ${file}`);
    } catch (err) {
      onError(`${describeApiError(err, 'The export')} No file was saved.`);
    } finally {
      setPending(false);
    }
  }

  return <Button variant="secondary" onClick={run} pending={pending}>{`Export the last ${EXPORT_HOURS} hours as CSV`}</Button>;
}
