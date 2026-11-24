import { OG_SIZE, OG_TYPE, ogImage } from '@/lib/ogImage';

export const size = OG_SIZE;
export const contentType = OG_TYPE;
export const alt = 'PHAEMOS: Blog';

export default function Image() {
  return ogImage('Blog', 'Notes on how PHAEMOS is built: the model, the firmware and the hardware.');
}
