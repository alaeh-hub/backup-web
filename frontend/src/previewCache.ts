import { api, PreviewInfo } from "./api";

/** What the Preview window already knows, so stepping to a file it has seen (or the one next to it) is instant instead of a
 *  wait for the server. Kept only while the window is open: reopening asks again, so it never shows a stale file. */
const cache = new Map<string, PreviewInfo>();
const inflight = new Map<string, Promise<PreviewInfo>>();

export const cached = (id: string) => cache.get(id);
export const clearInfoCache = () => cache.clear();
export function patchCached(id: string, patch: Partial<PreviewInfo>) { const x = cache.get(id); if (x) cache.set(id, { ...x, ...patch }); }

export function loadInfo(id: string): Promise<PreviewInfo> {
  const hit = cache.get(id);
  if (hit) return Promise.resolve(hit);
  let p = inflight.get(id);
  if (!p) {
    p = api<PreviewInfo>(`/api/preview/${id}`).then(x => {
      cache.set(id, x);
      if (cache.size > 14) cache.delete(cache.keys().next().value as string);   // the oldest goes first
      return x;
    }).finally(() => { inflight.delete(id); });
    inflight.set(id, p);
  }
  return p;
}

/** Warm the files on either side of the one being looked at: their details, and for a picture the picture itself. A file that
 *  has to come live from another PC is never fetched ahead of time. */
export function prefetch(now: PreviewInfo, ids: string[], i: number) {
  if (now.source?.startsWith("Live from")) return;
  for (const k of [i + 1, i - 1]) {
    const id = ids[k];
    if (!id) continue;
    loadInfo(id).then(x => { if (x.mode === "image" && x.raw) { const im = new Image(); im.src = x.raw; } }).catch(() => undefined);
  }
}
