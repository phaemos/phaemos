// a page's title, a line saying what the page is for and its controls, laid out the same everywhere

interface Props {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}

export default function PageHeader({ title, description, actions }: Props) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-surface-900 dark:text-surface-50">{title}</h1>
        {description && <p className="mt-1 text-sm text-surface-500 dark:text-surface-400">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
