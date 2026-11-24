import { OG_SIZE, OG_TYPE, ogImage } from '@/lib/ogImage';

export const size = OG_SIZE;
export const contentType = OG_TYPE;
export const alt = 'PHAEMOS: Status';

export default function Image() {
  return ogImage('Status', 'Whether the PHAEMOS API, database and cache answer right now.');
}
