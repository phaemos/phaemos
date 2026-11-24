// the CSV export: how far back it reaches and what the saved file is called. The API names the file after the
// machine id, which means nothing to a person, so the browser file is named from the machine name and the date.

export const EXPORT_HOURS = 24;

// the window start sent as from
export function exportFromTs(now: Date, hours: number = EXPORT_HOURS): string {
  return new Date(now.getTime() - hours * 3_600_000).toISOString();
}

// "boiler-room-pump-readings-last-24-hours-2026-11-22.csv". Anything that is not a letter or digit becomes a hyphen
// and a name with no usable characters falls back to "machine".
export function exportFileName(machineName: string, now: Date, hours: number = EXPORT_HOURS): string {
  const slug = machineName
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
    .replace(/-+$/g, '');
  const day = now.toISOString().slice(0, 10);
  return `${slug || 'machine'}-readings-last-${hours}-hours-${day}.csv`;
}
