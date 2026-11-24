// a small cache that lives as long as the worker's isolate. it is best effort: another isolate has
// its own copy. the Cache API is not used because it may do nothing on a workers.dev address.
export class TtlCache<T> {
  private entries = new Map<string, { value: T; at: number }>();
  private max: number;

  constructor(max: number) {
    this.max = max;
  }

  get(key: string, now: number, maxAgeMs: number): T | undefined {
    const hit = this.entries.get(key);
    if (!hit || now - hit.at > maxAgeMs) return undefined;
    return hit.value;
  }

  set(key: string, value: T, now: number): void {
    this.entries.delete(key);
    this.entries.set(key, { value, at: now });
    while (this.entries.size > this.max) {
      const oldest = this.entries.keys().next().value;
      if (oldest === undefined) break;
      this.entries.delete(oldest);
    }
  }

  delete(key: string): void {
    this.entries.delete(key);
  }

  get size(): number {
    return this.entries.size;
  }
}
