// the API's reference for a failed request, in small text, so that a person can quote it when they ask for help. Shown only when there
// is one (a network failure has none).
export default function RequestRef({ id }: { id?: string | null }) {
  if (!id) return null;
  return (
    <p className="text-meta text-surface-600 dark:text-surface-400">
      Reference <span className="num select-all">{id}</span>
    </p>
  );
}
