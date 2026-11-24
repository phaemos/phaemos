import OverviewPreview from '@/components/dashboard/OverviewPreview';

// the dashboard illustration on the home page: a plain caption and the description above it as real text, then the
// overview panels themselves with no frame around them. The illustration is the real overview fed from fixed sample data. It is
// decorative here, so it is hidden from assistive technology and taken out of the tab order. The sentence
// carries the meaning.
export default function HomePreview() {
  return (
    <div>
      <p className="max-w-[72ch] text-surface-700 dark:text-surface-300">
        The overview page shows fleet health, the active alerts grouped by machine and metric and a panel for each
        machine. The readings in this view are fixed sample data.
      </p>

      {/* the panels inside are the objects: no frame around them, so there is no panel in a panel */}
      <div aria-hidden="true" inert className="mt-8">
        <p className="label mb-3 text-surface-700 dark:text-surface-300">Overview, sample data</p>
        <OverviewPreview />
      </div>
    </div>
  );
}
