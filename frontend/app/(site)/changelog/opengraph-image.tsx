import { OG_SIZE, OG_TYPE, ogImage } from '@/lib/ogImage';

export const size = OG_SIZE;
export const contentType = OG_TYPE;
export const alt = 'PHAEMOS: Changelog';

export default function Image() {
  return ogImage('Changelog', 'Every PHAEMOS release with its date, a summary and the full notes.');
}
