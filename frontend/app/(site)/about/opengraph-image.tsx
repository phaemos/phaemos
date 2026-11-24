import { OG_SIZE, OG_TYPE, ogImage } from '@/lib/ogImage';

export const size = OG_SIZE;
export const contentType = OG_TYPE;
export const alt = 'PHAEMOS: One repository from the sensor to the ticket';

export default function Image() {
  return ogImage('One repository from the sensor to the ticket', 'What PHAEMOS is, how a reading travels through it and what works today.');
}
