import type { Alert } from '@/types';

interface Props {
  alert: Alert;
}

const severityStyle: Record<string, string> = {
  info: 'bg-blue-950/50 border-blue-500 text-blue-300',
  warning: 'bg-yellow-950/50 border-yellow-500 text-yellow-300',
  critical: 'bg-red-950/50 border-red-500 text-red-300',
};

export default function AlertBanner({ alert }: Props) {
  const style = severityStyle[alert.severity ?? 'info'];

  return (
    <div
      className={`border rounded-lg px-4 py-3 text-sm flex items-center gap-3 ${style}`}
    >
      <span className="font-semibold uppercase tracking-wide">{alert.severity}</span>
      <span>{alert.message}</span>
    </div>
  );
}
