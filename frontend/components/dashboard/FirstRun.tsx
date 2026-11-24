import { LinkButton } from '@/components/ui/Button';
import { adminTabHref } from '@/lib/adminTabs';
import type { Role } from '@/lib/role';

// the overview for a fleet with no machines: what to do first, one step at a time, in the order the product needs them;
// it replaces the empty machine grid and goes away by itself once a machine exists, because it is drawn only when the
// machine list came back empty. It reads nothing new: the role comes from the token the page already holds. Only the
// first step carries a button, so there is one obvious thing to do. Steps an admin alone can take are shown to admins.
export default function FirstRun({ role }: { role: Role | null }) {
  const admin = role === 'admin';
  const api = process.env.NEXT_PUBLIC_API_URL?.replace(/\/+$/, '') || 'https://your-api-address';

  const steps: { title: string; body: React.ReactNode; action?: React.ReactNode }[] = [
    {
      title: 'Add your first machine',
      body: admin
        ? 'Give it a name on the Machines page. Its API key is shown once, when the machine is created, so copy it then.'
        : 'An admin adds machines and gets each one its API key. Ask an admin in your team to add the first one.',
      action: admin ? <LinkButton href="/devices">Add a machine</LinkButton> : undefined,
    },
    {
      title: 'Send its first reading',
      body: (
        <>
          <p>Put the key in the node&apos;s firmware configuration. With no hardware yet, the simulator posts readings for any of the four node types:</p>
          <pre tabIndex={0} className="mt-3 overflow-x-auto rounded-md border border-surface-200 bg-surface-50 px-3 py-2 dark:border-surface-800 dark:bg-surface-950">
            <code className="text-sm text-surface-900 dark:text-surface-50">{`PHAEMOS_DEVICE_KEY=<key> phaemos-sim --node esp32 --url ${api}`}</code>
          </pre>
          <p className="mt-3">The machine shows as online here once its first reading arrives.</p>
        </>
      ),
    },
    {
      title: 'Decide what counts as a problem',
      body: admin
        ? 'Every reading is scored against a model of normal behaviour as it arrives. Alert rules add your own limits for a metric, under Admin.'
        : 'Every reading is scored against a model of normal behaviour as it arrives. An admin can add alert rules with your own limits.',
      action: admin ? (
        <a href={adminTabHref('alert-rules')} className="inline-flex min-h-[44px] items-center text-base text-brand-800 underline underline-offset-2 hover:no-underline dark:text-brand-400">
          Open alert rules
        </a>
      ) : undefined,
    },
  ];
  if (admin) {
    steps.push({
      title: 'Bring in your team',
      body: 'Invite people by email under Admin and pick a role for each: admin, technician or viewer. An invitation link lasts 48 hours.',
      action: (
        <a href={adminTabHref('users')} className="inline-flex min-h-[44px] items-center text-base text-brand-800 underline underline-offset-2 hover:no-underline dark:text-brand-400">
          Open people
        </a>
      ),
    });
  }

  return (
    <section aria-labelledby="first-run-title" className="rounded-lg border border-surface-200 bg-surface-0 dark:border-surface-800 dark:bg-surface-900">
      <div className="border-b border-surface-200 px-5 py-4 dark:border-surface-800">
        <h2 id="first-run-title" className="font-display text-lg font-semibold text-surface-900 dark:text-surface-50">
          Nothing is being monitored yet
        </h2>
        <p className="mt-1 max-w-[68ch] text-base text-surface-700 dark:text-surface-300">
          {steps.length} steps get the first machine reporting. This guide goes away once a machine is added.
        </p>
      </div>
      <ol className="divide-y divide-surface-200 dark:divide-surface-800">
        {steps.map((s, i) => (
          <li key={s.title} className="grid grid-cols-[2.25rem_minmax(0,1fr)] gap-x-3 px-5 py-4">
            {/* the first step is filled and the rest are outlined. Each says its number, so the order never rests on colour */}
            <span
              aria-hidden="true"
              className={`tnum mt-0.5 inline-flex h-8 w-8 items-center justify-center rounded-full text-sm font-semibold ${
                i === 0
                  ? 'bg-brand-700 text-white dark:bg-brand-400 dark:text-surface-950'
                  : 'border-2 border-surface-500 text-surface-700 dark:border-surface-400 dark:text-surface-300'
              }`}
            >
              {i + 1}
            </span>
            <div className="min-w-0">
              <h3 className="text-base font-semibold text-surface-900 dark:text-surface-50">
                <span className="sr-only">Step {i + 1} of {steps.length}: </span>
                {s.title}
              </h3>
              <div className="mt-1 max-w-[68ch] text-base text-surface-700 dark:text-surface-300">{typeof s.body === 'string' ? <p>{s.body}</p> : s.body}</div>
              {s.action && <div className="mt-3">{s.action}</div>}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
