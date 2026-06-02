interface EmptyStateProps {
  icon?: string;
  heading: string;
  subMessage?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
}

export default function EmptyState({ icon = '📭', heading, subMessage, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
      <span className="text-5xl mb-4" role="img" aria-hidden="true">{icon}</span>
      <h3 className="text-lg font-semibold text-surface-900 dark:text-surface-50 mb-1">
        {heading}
      </h3>
      {subMessage && (
        <p className="text-sm text-surface-400 dark:text-surface-500 max-w-xs">
          {subMessage}
        </p>
      )}
      {action && (
        <button
          onClick={action.onClick}
          className="mt-4 bg-brand-600 hover:bg-brand-700 active:scale-95 text-white px-4 py-2 rounded-lg text-sm font-medium transition-all duration-150"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
