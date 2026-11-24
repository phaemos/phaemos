// every call to another service goes through here: a time-out, a size limit and no redirects.
export class UpstreamError extends Error {
  kind: "timeout" | "network" | "status" | "size" | "parse";
  status: number;

  constructor(kind: UpstreamError["kind"], status = 0) {
    super(kind);
    this.kind = kind;
    this.status = status;
  }
}

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export interface Bounds {
  timeoutMs: number;
  maxBytes: number;
}

export async function fetchBounded(
  doFetch: FetchLike,
  url: string,
  init: RequestInit,
  bounds: Bounds,
): Promise<{ status: number; body: string }> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), bounds.timeoutMs);
  try {
    const res = await doFetch(url, { ...init, signal: controller.signal, redirect: "manual" });
    const declared = Number(res.headers.get("content-length") ?? "0");
    if (declared > bounds.maxBytes) {
      await res.body?.cancel();
      throw new UpstreamError("size", res.status);
    }
    const reader = res.body?.getReader();
    const chunks: Uint8Array[] = [];
    let total = 0;
    if (reader) {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        total += value.byteLength;
        if (total > bounds.maxBytes) {
          await reader.cancel();
          throw new UpstreamError("size", res.status);
        }
        chunks.push(value);
      }
    }
    const all = new Uint8Array(total);
    let at = 0;
    for (const c of chunks) {
      all.set(c, at);
      at += c.byteLength;
    }
    return { status: res.status, body: new TextDecoder().decode(all) };
  } catch (err) {
    if (err instanceof UpstreamError) throw err;
    throw new UpstreamError(controller.signal.aborted ? "timeout" : "network");
  } finally {
    clearTimeout(timer);
  }
}

export function parseJson(body: string): unknown {
  try {
    return JSON.parse(body);
  } catch {
    throw new UpstreamError("parse");
  }
}
