// the one surface every panel sits on, with an optional header row for a title, a note and actions

interface Props {
  title?: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}

export default function Card({ title, description, actions, children, className = '', bodyClassName = 'p-4' }: Props) {
  return (
    <section className={`rounded-lg border border-surface-200 dark:border-surface-800 bg-white dark:bg-surface-900 ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-surface-200 dark:border-surface-800 px-4 py-3">
          <div>
            {title && <h2 className="text-sm font-semibold text-surface-900 dark:text-surface-50">{title}</h2>}
            {description && <p className="mt-0.5 text-xs text-surface-500 dark:text-surface-400">{description}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}
