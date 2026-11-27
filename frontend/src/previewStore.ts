import { useSyncExternalStore } from "react";

/** What the Preview window is showing: the ids of the files in the list it was opened from, and which one is open.
 *  Any list can open it without passing anything down, and the arrow keys step through that list. */
interface State { ids: string[]; i: number }
let state: State | null = null;
const subs = new Set<() => void>();
const emit = () => subs.forEach(f => f());

export function openPreview(ids: string[], id: string) {
  const i = ids.indexOf(id);
  state = { ids: i < 0 ? [id] : ids, i: Math.max(i, 0) };
  emit();
}
export function closePreview() { state = null; emit(); }
export function goPreview(i: number) {
  if (!state || i < 0 || i >= state.ids.length || i === state.i) return;
  state = { ...state, i };
  emit();
}
export function stepPreview(d: number) {
  if (!state) return;
  const i = state.i + d;
  if (i < 0 || i >= state.ids.length) return;
  state = { ...state, i };
  emit();
}
export const usePreviewState = () => useSyncExternalStore(cb => { subs.add(cb); return () => { subs.delete(cb); }; }, () => state);
