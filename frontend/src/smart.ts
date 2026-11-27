/** Smart search for lists that are filtered on screen. The server uses the same rules (backend/smartsearch.py):
 *  every word must match in any order, "a phrase" must match exactly, -word leaves matches out, .pdf or ext:pdf picks a type, type:spreadsheet (or images, videos, audio...) a kind of file,
 *  >10mb and <1gb pick a size, and when nothing matches a word with a typo or two is still found. */
import kinds from "./kinds.json";

const norm = (s: string) => s.toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
const UNIT: Record<string, number> = { "": 1, b: 1, k: 1e3, kb: 1e3, m: 1e6, mb: 1e6, g: 1e9, gb: 1e9, t: 1e12, tb: 1e12 };

function within(a: string, b: string, limit: number): boolean {
  if (Math.abs(a.length - b.length) > limit) return false;
  let p2: number[] | null = null, p = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const c = [i];
    for (let j = 1; j <= b.length; j++) {
      let v = Math.min(p[j] + 1, c[j - 1] + 1, p[j - 1] + (a[i - 1] !== b[j - 1] ? 1 : 0));
      if (p2 && i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) v = Math.min(v, p2[j - 2] + 1);
      c.push(v);
    }
    if (Math.min(...c) > limit && (!p2 || Math.min(...p) > limit)) return false;
    p2 = p; p = c;
  }
  return p[b.length] <= limit;
}

const KIND_EXTS = kinds.kinds as Record<string, string[]>, KIND_WORDS = kinds.words as Record<string, string[]>;

/** The extensions a type: or ext: value stands for: a kind word (spreadsheet, images) is every extension of that kind, anything
 *  else is one extension. Comma-separated values mix both. Same rules and the same lists as the server (backend/smartsearch.py). */
export function expandTypes(value: string): string[] {
  const out = new Set<string>();
  for (const raw of norm(value).split(",")) {
    const item = raw.replace(/^[ .]+|[ .]+$/g, "");
    if (!item) continue;
    for (const k of KIND_WORDS[item] ?? []) for (const e of KIND_EXTS[k]) out.add("." + e);
    if (!KIND_WORDS[item]) out.add("." + item);
  }
  return [...out];
}

export interface Parsed { terms: string[]; phrases: string[]; exclude: string[]; exts: string[]; min?: number; max?: number; empty: boolean; fuzzy: boolean }

export function parse(text: string): Parsed {
  const r: Parsed = { terms: [], phrases: [], exclude: [], exts: [], empty: true, fuzzy: false };
  for (const tok of text.match(/-?"[^"]*"|\S+/g) ?? []) {
    const neg = tok.startsWith("-") && tok.length > 1, body = neg ? tok.slice(1) : tok;
    if (body.startsWith('"')) { const w = norm(body.replace(/"/g, "")).trim(); if (w) (neg ? r.exclude : r.phrases).push(w); continue; }
    const m = /^(?:size)?([<>]=?)(\d+(?:\.\d+)?)\s*(b|kb|mb|gb|tb|k|m|g|t)?$/i.exec(tok);
    if (m) { const n = parseFloat(m[2]) * UNIT[(m[3] ?? "").toLowerCase()]; if (m[1][0] === ">") r.min = Math.max(r.min ?? 0, n); else r.max = Math.min(r.max ?? Infinity, n); continue; }
    const e = /^(?:ext|type|kind):(.+)$/i.exec(body);
    if (e && !neg) { r.exts.push(...expandTypes(e[1])); continue; }
    if (/^\.[a-z0-9]{1,8}$/i.test(body) && !neg) { r.exts.push(norm(body)); continue; }
    const w = norm(body); if (w) (neg ? r.exclude : r.terms).push(w);
  }
  r.empty = !(r.terms.length || r.phrases.length || r.exclude.length || r.exts.length || r.min !== undefined || r.max !== undefined);
  r.fuzzy = r.terms.some(t => t.length >= 4);
  return r;
}

export function matches(q: Parsed, text: string, opts: { size?: number; ext?: string; fuzzy?: boolean } = {}): boolean {
  const t = norm(text), ext = (opts.ext ?? "").toLowerCase();
  if (q.exts.length && !q.exts.includes(ext)) return false;
  if (opts.size !== undefined && ((q.min !== undefined && opts.size < q.min) || (q.max !== undefined && opts.size > q.max))) return false;
  if (q.phrases.some(p => !t.includes(p)) || q.exclude.some(x => t.includes(x))) return false;
  let squashed: string | null = null, words: string[] | null = null;
  for (const w of q.terms) {
    if (t.includes(w)) continue;
    squashed ??= (t.match(/[a-z0-9]+/g) ?? []).join("");
    if (squashed.includes(w)) continue;
    if (!(opts.fuzzy && w.length >= 4)) return false;
    words ??= t.match(/[a-z0-9]+/g) ?? [];
    const limit = w.length <= 6 ? 1 : 2;
    if (!words.some(x => within(w, x, limit) || within(w, x.slice(0, w.length), limit))) return false;
  }
  return true;
}

/** The items that fit the search; if none do, the ones that fit when a typo or two is forgiven. */
export function smartFilter<T>(items: T[], query: string, text: (x: T) => string, opts?: (x: T) => { size?: number; ext?: string }): T[] {
  const q = parse(query);
  if (q.empty) return items;
  const run = (fuzzy: boolean) => items.filter(x => matches(q, text(x), { ...opts?.(x), fuzzy }));
  const a = run(false);
  return a.length || !q.fuzzy ? a : run(true);
}

export const searchHelp = 'Type words in any order. Use "quotes" for a phrase, -word to leave one out, .pdf or type:images for a type, >10mb or <1gb for a size.';
