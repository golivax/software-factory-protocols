export interface CacheReply {
  key: string;
  value: string;
}

export async function fetchCached(key: string): Promise<CacheReply> {
  const res = await fetch("/cache?key=" + key);
  const value = await res.text();
  return { key, value };
}
