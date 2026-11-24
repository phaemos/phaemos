import Button from './Button';

interface EmptyStateProps {
  heading: string;
  subMessage?: string;
  action?: {
    label: string;
    onClick?: () => void;
    href?: string;
  };
}

// says what is missing and what to do next, so an empty panel is never a dead end. Left-aligned so it sits
// naturally inside a table panel. It means "the request worked and there is nothing": a failed request uses ErrorNotice.
export default function EmptyState({ heading, subMessage, action }: EmptyStateProps) {
  return (
    <div className="px-4 py-8">
      <h3 className="text-base font-semibold text-surface-900 dark:text-surface-50">{heading}</h3>
      {subMessage && <p className="mt-1 max-w-prose text-base text-surface-600 dark:text-surface-400">{subMessage}</p>}
      {action && (
        <div className="mt-4">
          {action.href ? (
            <Button href={action.href}>{action.label}</Button>
          ) : (
            <Button onClick={action.onClick}>{action.label}</Button>
          )}
        </div>
      )}
    </div>
  );
}
