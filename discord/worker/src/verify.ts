// signature check for Discord interactions.
//
// Discord's documentation (Interactions Overview, "Security and Authorization", read 22 November
// 2026) says each interaction is sent with "X-Signature-Ed25519 as a signature" and
// "X-Signature-Timestamp as a timestamp". It says an app "must validate the request each time you
// receive an interaction". It also says "If the signature fails validation, your app should
// respond with a 401 error code". The signed message is the timestamp followed by the raw request
// body, checked with Ed25519 against the application's public key.
// the page states no limit on body size or on timestamp age. the limits in app.ts are our own.

const SIGNATURE_BYTES = 64;
const KEY_BYTES = 32;

function hexToBytes(hex: string, length: number): Uint8Array<ArrayBuffer> | null {
  if (hex.length !== length * 2 || !/^[0-9a-fA-F]+$/.test(hex)) return null;
  const out = new Uint8Array(length);
  for (let i = 0; i < length; i++) out[i] = Number.parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

export function isValidPublicKey(hex: string): boolean {
  return hexToBytes(hex, KEY_BYTES) !== null;
}

let keyCache: { hex: string; key: CryptoKey } | null = null;

async function importKey(publicKeyHex: string): Promise<CryptoKey | null> {
  if (keyCache && keyCache.hex === publicKeyHex) return keyCache.key;
  const raw = hexToBytes(publicKeyHex, KEY_BYTES);
  if (!raw) return null;
  const key = await crypto.subtle.importKey("raw", raw, { name: "Ed25519" }, false, ["verify"]);
  keyCache = { hex: publicKeyHex, key };
  return key;
}

export async function verifySignature(
  publicKeyHex: string,
  signatureHex: string,
  timestamp: string,
  body: Uint8Array<ArrayBuffer>,
): Promise<boolean> {
  try {
    const signature = hexToBytes(signatureHex, SIGNATURE_BYTES);
    if (!signature) return false;
    const key = await importKey(publicKeyHex);
    if (!key) return false;
    const stamp = new TextEncoder().encode(timestamp);
    const message = new Uint8Array(stamp.byteLength + body.byteLength);
    message.set(stamp, 0);
    message.set(body, stamp.byteLength);
    return await crypto.subtle.verify({ name: "Ed25519" }, key, signature, message);
  } catch {
    return false;
  }
}
