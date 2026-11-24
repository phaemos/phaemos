import { OG_SIZE, OG_TYPE, ogImage } from '@/lib/ogImage';

export const size = OG_SIZE;
export const contentType = OG_TYPE;
export const alt = 'PHAEMOS: Contact';

export default function Image() {
  return ogImage('Contact', 'Send us a question or feedback.');
}
