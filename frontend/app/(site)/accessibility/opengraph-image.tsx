import { OG_SIZE, OG_TYPE, ogImage } from '@/lib/ogImage';

export const size = OG_SIZE;
export const contentType = OG_TYPE;
export const alt = 'PHAEMOS: Accessibility statement';

export default function Image() {
  return ogImage('Accessibility statement', 'How accessible the website and dashboard are and how to tell us about a problem.');
}
