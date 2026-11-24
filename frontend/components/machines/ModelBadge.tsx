import Link from 'next/link';
import StatusBadge from '@/components/ui/StatusBadge';
import Time from '@/components/ui/Time';
import { modelView, refusalFor } from '@/lib/modelState';
import type { Device, MlStatus } from '@/types';

interface Props {
  device: Pick<Device, 'id' | 'model'>;
  // GET /ml/status, for the refusal behind a machine that has no model. Absent while it loads or when it failed.
  status?: MlStatus | null;
  // write what it means for alerts under the badge
  detail?: boolean;
  // a table row stretches its name link over the whole row, so a link inside needs to sit above it
  raised?: boolean;
  // false on the model page itself, where the link would lead nowhere
  link?: boolean;
}

// the anomaly model's state for one machine: a shape and a word (Ready, Learning with its hours, Legacy, No model, Model error). The
// word is always shown. A machine with no model or a model that will not load leads to the model page, which explains why.
export default function ModelBadge({ device, status, detail = false, raised = false, link = true }: Props) {
  const v = modelView(device.model, refusalFor(status, device.id));
  return (
    <span className="flex flex-col items-start gap-0.5">
      <StatusBadge status={v.status} label={v.label} />
      {detail && <span className="max-w-[60ch] text-sm text-surface-800 dark:text-surface-200">{v.detail}</span>}
      {v.kind === 'refused' && device.model?.refused_at && <span className="text-sm text-surface-800 dark:text-surface-200">Refused <Time value={device.model.refused_at} format="datetime" />.</span>}
      {v.toModelPage && link && (
        <Link href="/models" className={`inline-flex min-h-[44px] items-center text-meta font-medium text-brand-800 underline-offset-2 hover:underline dark:text-brand-400 ${raised ? 'relative z-10' : ''}`}>
          Why, on the model page<span className="sr-only"> for {v.label}</span>
        </Link>
      )}
    </span>
  );
}
