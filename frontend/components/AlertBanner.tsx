import type { Alert } from '@/types';

interface Props {
  alert: Alert;
}

const severityStyle: Record<string, string> = {
  info: 'bg-blue-50 dark:bg-blue-950/50 border-blue-400 dark:border-blue-500 text-blue-700 dark:text-blue-300',
  warning: 'bg-yellow-50 dark:bg-yellow-950/50 border-yellow-400 dark:border-yellow-500 text-yellow-700 dark:text-yellow-300',
  critical: 'bg-red-50 dark:bg-red-950/50 border-red-400 dark:border-red-500 text-red-700 dark:text-red-300',
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
