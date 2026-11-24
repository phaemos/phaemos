import Button from '@/components/ui/Button';

interface Props {
  // the first row number on this page, counting from 0
  skip: number;
  shown: number;
  pageSize: number;
  onChange: (skip: number) => void;
  what: string;
  // how many rows exist, from the X-Total-Count header, when the API sent one
  total?: number | null;
}

// previous and next for a list the API pages with skip and limit. The API does not report a total, so a full page
// is the only sign that there may be more, unless the list sends its total.
export default function Pager({ skip, shown, pageSize, onChange, what, total = null }: Props) {
  const atEnd = total !== null ? skip + shown >= total : shown < pageSize;
  return (
    <nav aria-label={`${what} pages`} className="flex items-center justify-between gap-3 border-t border-surface-200 px-4 py-2 dark:border-surface-800">
      <Button variant="ghost" size="small" onClick={() => onChange(Math.max(0, skip - pageSize))} disabled={skip === 0}>Previous</Button>
      <p className="tnum text-meta text-surface-600 dark:text-surface-400" aria-live="polite">
        {shown === 0 ? 'No more rows' : `Rows ${skip + 1} to ${skip + shown}${total !== null ? ` of ${total}` : ''}`}
      </p>
      <Button variant="ghost" size="small" onClick={() => onChange(skip + pageSize)} disabled={atEnd}>Next</Button>
    </nav>
  );
}
