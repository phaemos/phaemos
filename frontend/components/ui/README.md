# UI system

Every page builds from these pieces. Tokens and the global rules (focus ring, reduced motion, table styles, control radius and 44 px minimum) live in `app/globals.css` and `tailwind.config.ts`. Do not write a new button, status map, date format, spinner or form control: use the one here. `lib/designRules.test.mts` fails the build of the tests when a rule below is broken.

## Rules for page builders

**Vocabulary.** The thing being monitored is a **machine**. The board attached to it is a **node**. The word **device** never appears in text a user reads. Routes (`/devices`), API paths and type names stay as they are. Sentence case everywhere ("Upload firmware", not "Upload Firmware").

**Titles.** The root layout sets the template `%s | PHAEMOS`. A page exports only its own name: `export const metadata = { title: 'About' }`, never `'About - PHAEMOS'`. A client page cannot export metadata, so give its route a `layout.tsx` that does (see `app/(app)/*/layout.tsx`) or split the page into a server page and a client component. A group layout sets no title of its own because the template stops there otherwise.

**Type scale.** Sizes are in rem so browser zoom and the reader's own text size work. Nothing a person reads or uses is under 13 px.

| Size | Class | Use |
|---|---|---|
| 13 px | `text-meta` | metadata, table headers, small button labels, group labels (`.label`) |
| 14 px | `text-sm` | table cells and dense secondary text (status words, panel descriptions, machine card lines) |
| 16 px | `text-base` | body text, controls, labels, nav. The default |
| 18 px | `text-lg` | a lead sentence, a figure with words |
| 20 px | `text-xl` | the app page title (`PageHeader`) |
| 24 px | `text-2xl` | a section title on the public site |
| 28 px | `text-3xl` | a large figure |
| 36 to 48 px | `text-4xl md:text-5xl` | the public page title (`SiteHeading`) |

Weights are `font-normal`, `font-medium` and `font-semibold`. No `font-bold`. Headings balance and paragraphs avoid a one-word last line (`text-wrap` in the base styles). Text columns stop at 72 characters. A number and its unit are tied with a non-breaking space: use `formatReading` from `@/lib/units`.

**Monospace is for code and data only.** Readings with units, ids, keys, commands and line formats use the `num` class or a `code` element. Dates, times, counts, versions, headings, navigation, labels and table headers are the sans face. Use `tnum` for tabular figures in the sans face. There are no uppercase labels: a heading says what the section is on its own.

**Motion.** Hover and press change a colour in 150 ms. Menus, tabs and list rows do not animate. Dialogs and the phone drawer take 200 ms with `cubic-bezier(0.23, 1, 0.32, 1)` on transform and opacity only (`drawer-in` and `dialog[open]` in `globals.css`). Never `transition-all`. Nothing loops except the spinner, which only shows after 200 ms and stays at least 300 ms inside a button. Skeletons are still. `prefers-reduced-motion` turns off every animation and transition.

**Hover.** `hover:` classes mean "can hover and has a fine pointer". `@custom-variant hover` in `app/globals.css` sets that once, so a tap never leaves a stuck hover state. Write plain `hover:` classes. The focus ring has no transition and appears at once.

**Failure is not emptiness.** A failed request shows `ErrorNotice`. `EmptyState` means the request worked and there was nothing.

**One cue per surface.** A border or a shadow, never both. The site has no shadows. Never a panel inside a panel. Radius is 6 px on controls and 8 px on panels. No pills (only a numeric count may be round). Icons are for recognising a control and never decoration: the sidebar, the menu and close buttons, the theme toggle (a sun while the dark theme is on, a moon while the light one is), the external-link mark on a link that opens another site, a search field's magnifier, copy buttons, show and hide on a password, the chevron on anything that expands and the spinner. One set, one stroke weight, each with a real accessible name. None beside a heading or in a list.

**Fonts.** The two typefaces live only in `app/layout.tsx`, behind the CSS variables `--typeface-sans` and `--typeface-mono`. Swapping a face is one edit there. They are self-hosted through `next/font`.

## Components

| Import | Props | What it is |
|---|---|---|
| `@/components/ui/Button` default `Button` | `variant` (`primary` `secondary` `ghost` `danger`), `size` (`default` `small`), `pending`, `icon`, plus button attributes | The only button. `default` is 44 px high. `small` is 32 px high with a 44 px hit area from a pseudo-element, for dense rows. `pending` keeps the width, sets `aria-busy`, keeps focus, ignores clicks and shows its spinner after 200 ms. Passing `href` renders a `LinkButton` |
| `@/components/ui/Button` named `LinkButton` | `href`, `variant`, `size`, `external`, `pending` | A link that looks like a button. Navigate with it. Do something with `Button` |
| `@/components/ui/Panel` | `title`, `description`, `actions`, `headingLevel`, `bodyClassName` | Wraps one discrete object: hairline border, 8 px radius, no shadow, optional header row. Do not wrap page sections and never nest one in another |
| `@/components/ui/StatusBadge` | `status`, `label` | Shape plus word for any key in `lib/status.ts`. Also exports `StatusShape` and `statusShape()` |
| `@/components/ui/Badge` | `tone`, `shape`, `status`, `children` | Plain hairline label for a category (a role, a rule type) |
| `@/components/ui/Segmented` | `options`, `value`, `onChange`, `label`, `hideLabel`, `className` | One-of-many control, 44 px high. Its label shows above it in the style `Field` gives a label. Arrow keys, Home and End. When the options do not fit the track scrolls sideways and never wraps |
| `@/components/ui/Tabs` | `items`, `value`, `label`, `onChange`, `idPrefix` | Underlined tabs. Give every item an `href` for links that work without script |
| `@/components/ui/DataTable` | `caption`, `maxHeightClass`, `framed`, `minWidth` | Wraps a table in the `.data-table` styles: sticky header, 13 px sentence-case headers, 14 px cells and 44 px rows for every table. Rows do not tint on hover: add `row-action` to a `tr` that does something when pressed. A reading with a unit gets the `num` class on its `td` |
| `@/components/ui/PageHeader` | `title`, `description`, `actions` | The app page's h1 at 20 px semibold, an optional description and actions on the right |
| `@/components/ui/SiteHeading` | `title`, `lead` | The head of a public page: the h1 at 36 px (48 px from 768 px) and one lead sentence |
| `@/components/ui/BackLink` | `href`, `children` | "Back to {children}" above the h1 of a nested page |
| `@/components/ui/EmptyState` | `heading`, `subMessage`, `action` | Says what is missing and what to do next. Left-aligned |
| `@/components/ui/ErrorNotice` | `message`, `detail`, `onRetry`, `retryLabel`, `pending` | Inline notice for a failed request with a "Try again" button. `role="alert"` |
| `@/components/ui/Skeleton` | `Skeleton`, `SkeletonGroup`, `SkeletonRows` | The one still placeholder. Wrap custom skeletons in `SkeletonGroup label="Loading machines"` so it is announced once |
| `@/components/ui/Spinner` | `label`, `size`, `decorative` | The one spinner. It shows after 200 ms. Announced as `role="status"` |
| `@/components/ui/Time` | `value`, `format` (`date` `datetime` `exact` `relative`), `now`, `fallback` | A `time` element in the sans face with tabular figures. The only way a date or time reaches the screen |
| `@/components/ui/CopyValue` | `value`, `what` | An id on one line in mono with a Copy button (copy icon, then a tick), cut in the middle when narrow |
| `@/components/ui/Field` | `label`, `hint`, `error`, `required`, `id`, render function | Ties a label to its control by id and wires `aria-describedby` and `aria-invalid`. The error is text |
| `@/components/ui/Input` named `Input`, `PasswordInput`, `Select`, `Textarea` | `label`, `hint`, `error`, `required`, `wrapperClassName` plus the element's attributes | Labelled controls built on `Field`, 44 px high, 3:1 border. A `type="search"` input shows a magnifier. `PasswordInput` has a show and hide button |
| `@/components/ui/Checkbox` | `label`, `hint` plus input attributes | The whole row is the label, so the hit area is 44 px |
| `@/components/ui/ConfirmDialog` | `open`, `title`, `children`, `confirmLabel`, `confirmIcon`, `cancelLabel`, `onCancel`, `onConfirm`, `pending`, `destructive` | For a destructive action. Name the object and the action in the title and the button ("Delete Walk Pump 1"). Native dialog: focus trapped, Escape closes, focus returns. Cancel is first and focused |
| `@/components/ui/ErrorBoundary` | | Wraps a group of pages. Also exports `ErrorPanel` |
| `@/components/ui/ReadOnlyNote` | `children` | Says once, in words, why a control is missing for a view-only account (a viewer reads and does not change) |
| `@/components/ui/FilterDisclosure` | `count`, `children` | Below 768 px the filters sit behind one "Filters" button that says how many are active and starts open only when one is set. From 768 px they are always shown |
| `@/components/machines/MachineStatus` | `MachineBadge`, `LinkBadge`, default `MachineStatus` | The two facts about a machine, each a shape and a word: what it is (Healthy, Warning, Fault or Unknown, with its reason in words) and how it is watched (Online, Late or Offline). Use these and never `device.status` |
| `@/components/ui/Logo` | `showWord`, `size` | Emblem and wordmark in both themes |
| `@/components/ui/Wordmark` | `height` (rem), `className` | The drawn PHAEMOS lettering as inline SVG, named "PHAEMOS", in the parent's text colour |
| `@/components/ui/ThemeToggle` | `variant` (`bar` for a header, `menu` for a menu row) | Icon button (menu row: icon and words) that switches the theme and the `theme-color` of the browser chrome. The icon and the name come from the theme class through CSS, so nothing flashes or shifts |
| `@/components/ui/Toast`, `@/hooks/useToast` | | Success and info messages. A failed request uses `ErrorNotice`, not a toast |
| `@/components/ui/icons` | `size` | Inline SVG icons: sidebar, menu buttons, spinner and the external-link mark |

## Helpers

| Import | What it does |
|---|---|
| `@/lib/format` | `formatDate` (22 Nov 2026), `formatDateTime` (22 Nov 2026, 00:10), `formatDateTimeExact` (adds seconds, for a `title` only), `formatRelative(value, now?)`, `plural`, `roleWord`. Use `Time` in JSX |

**One date and time form.** A moment reads "22 Nov 2026, 00:10" on the 24 hour clock, a day reads "22 Nov 2026" and something recent may read "5 min ago". Seconds never show in the text: they live in the `title`. A relative time always carries its exact time as text for assistive technology and, with `showExact`, as visible text after it (use that in a detail panel or a table of machines, where touch and keyboard users cannot reach a `title`). "Last updated", "reported", "since" and every other label use `Time` or `formatDateTime`, never `toLocaleString`.
| `@/lib/units` | `formatReading(value, unit, digits)` ties a number to its unit with a non-breaking space. `NBSP` and `tieUnit` |
| `@/lib/machineState` | `linkOf`, `machineStatus`, `fleetBucket`, `countFleet`, `fleetWord`, `fleetSentence`, `faultsOf`, `faultSince`: the machine's state and link from `link_state`, its active alerts and its sensor faults. The fleet bar, its legend and the health word all come from `countFleet` |
| `@/lib/links` | `siteHref(path)`, `appHref(path)`, `appPath(path)`, `dashboardCta`: every link between the public site and the dashboard. Absolute in split mode, relative otherwise |
| `@/lib/status` | `STATUS`, `MACHINE_STATUS`, `ALERT_SEVERITY`, `TICKET_STATUS`, `TICKET_PRIORITY` and `statusInfo(key)`: a word, a shape and a tone for each |
| `@/hooks/useApiResource` | `useApiResource<T>(path, { params, intervalMs, what, enabled })` returns `{ data, error, loading, retry }` |
| `@/hooks/useRole` | `useRole()` and `useCanWrite()`: false for a viewer. Hide a write control for a viewer and say why with `ReadOnlyNote` |
| `@/hooks/useSpinnerVisible` | `useSpinnerVisible(active)`: true 200 ms after work starts and for at least 300 ms once shown |
| `@/lib/apiError` | `describeApiError(err, what)`: one plain sentence for a failed request |
| `@/lib/cn` | `cn(...)` joins class names and lets the last Tailwind utility win |

A list page, in full:

```tsx
const { data, error, loading, retry } = useApiResource<Machine[]>('/devices', { what: 'The machines', intervalMs: 5000 });
if (loading) return <SkeletonRows rows={5} label="Loading machines" />;
if (error && !data) return <ErrorNotice message={error} onRetry={retry} />;
if (data?.length === 0) return <EmptyState heading="No machines yet" subMessage="Add a node and it appears here." />;
```

State that a person may want to share (filters, tabs, sort order) lives in the address, as on the alerts, tickets and machines pages.

## Shell

`app/(app)/layout.tsx` renders `AppShell`: a 240 px sidebar (a 64 px icon rail from 768 to 1023 px and a drawer below 768 px) holding the emblem, the fleet status, three groups, Docs and Changelog and the user menu. Every page sits in one outer box (`max-w-7xl p-6`, left-aligned) that the shell owns, so pages add only their own spacing. From 1024 px there is no top bar. Below 1024 px a 48 px bar shows the menu button, the page name as plain text and the fleet status.

| ProofDialog.tsx | A dialog that asks the signed-in person to prove it is them again before an action that could be misused by a stolen session. Props: `open`, `title`, `confirmLabel`, `children` (what is about to happen), `onCancel`, `run(proof)` (sends the request with `{password?, code?}` added to it and throws the API's error), `onDone`, `returnTo` (a dashboard path a provider account comes back to) and the optional `destructive` and `note`. It reads `/auth/me` itself to know whether to ask for a password, a code or a provider sign-in, shows each 400 beside its field and a 429 plainly and never retries a proof |
| Countdown.tsx | A wait the person sees running down. A screen reader hears it twice only (at the start and at the end). Used for a 429 with `Retry-After` |
