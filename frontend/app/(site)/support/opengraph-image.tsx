import { OG_SIZE, OG_TYPE, ogImage } from '@/lib/ogImage';

export const size = OG_SIZE;
export const contentType = OG_TYPE;
export const alt = 'PHAEMOS: Support';

export default function Image() {
  return ogImage('Support', 'Where to ask a question, report a bug and fix the common setup problems.');
}
