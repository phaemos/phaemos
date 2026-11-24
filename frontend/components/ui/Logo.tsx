import Image from 'next/image';
import Wordmark from './Wordmark';

// the emblem and wordmark. The light emblem sits on light surfaces and the dark one on dark surfaces. The wordmark is the drawn
// lettering of the brand artwork (Wordmark.tsx), sized against the emblem the way the horizontal logo on the brand board is.
// the style sets both sides explicitly because the CSS reset gives images height: auto, which makes Next warn that
// only one of width and height was changed.
export default function Logo({ showWord = true, size = 28 }: { showWord?: boolean; size?: number }) {
  const dims = { width: size, height: size };
  return (
    <>
      <span className="inline-flex shrink-0" aria-hidden="true">
        <Image src="/brand/phaemos-emblem-light.png" alt="" width={size} height={size} style={dims} className="dark:hidden" />
        <Image src="/brand/phaemos-emblem-dark.png" alt="" width={size} height={size} style={dims} className="hidden dark:block" />
      </span>
      {showWord ? (
        <Wordmark height={(size * 0.54) / 16} className="text-surface-950 dark:text-surface-50" />
      ) : (
        <span className="sr-only">PHAEMOS</span>
      )}
    </>
  );
}
