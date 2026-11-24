// keyset paging (docs/api-reference.md, "Order and keyset paging"). A page is newest first and ends in the row's id. A full page carries
// the cursor of its last row in X-Next-Before, `<ISO time>,<id>`, which is sent back as `before` for the next page. A page shorter than the
// limit is the last. No import, so the tests can load it.

// the cursor for the next page: the header when the page was full and none when it was short or the header is missing
export function nextCursor(header: unknown, pageLength: number, pageSize: number): string | null {
  if (pageLength < pageSize) return null;
  return typeof header === 'string' && header.length > 0 ? header : null;
}

export interface Merged<T> {
  items: T[];
  cursor: string | null;
  done: boolean;
  // true when rows from the older pages already read were kept
  keptOlder: boolean;
}

// joins a freshly read first page to what was read before. Rows already read that are older than the last row of the new page are kept, so
// an older page stays loaded and rows newer than it are taken from the new page alone, so a row that left the list (an alert resolved)
// leaves it. A short first page is the whole list. Cursors compare as text because the API writes them in one fixed form.
export function mergeFirstPage<T extends { id: string }>(page: readonly T[], existing: readonly T[], cursorOf: (item: T) => string, pageSize: number): Merged<T> {
  if (page.length < pageSize) return { items: [...page], cursor: null, done: true, keptOlder: false };
  const last = cursorOf(page[page.length - 1]);
  const ids = new Set(page.map((p) => p.id));
  const older = existing.filter((e) => !ids.has(e.id) && cursorOf(e) < last);
  return { items: [...page, ...older], cursor: null, done: false, keptOlder: older.length > 0 };
}
