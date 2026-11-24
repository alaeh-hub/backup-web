export async function api<T = unknown>(url: string, method = "GET", body?: unknown): Promise<T> {
  const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  if (r.status === 401) window.dispatchEvent(new Event("unauth"));
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error ?? r.statusText);
  return r.status === 204 ? (undefined as T) : r.json();
}
export const fmt = (n: number | null | undefined) => {
  const v = n ?? 0;
  return v >= 1e9 ? (v / 1e9).toFixed(2) + " GB" : v >= 1e6 ? (v / 1e6).toFixed(1) + " MB" : v >= 1e3 ? (v / 1e3).toFixed(1) + " KB" : v + " B";
};

export type Status = "new" | "modified" | "backed_up";
export const label: Record<Status, string> = { new: "New", modified: "Modified", backed_up: "Backed up" };
export interface FileRow { id: string; path: string; size: number; mtime: number; selected: number; review: boolean; status: Status }
export interface Device { folder: string; name: string; user: string; first_backup: string | null; last_backup: string | null; this_pc: boolean }
export interface DeviceDrive { dest: string; reachable: boolean; label: string; devices: Device[] }
export interface Dest { path: string; label?: string; pc_folder?: string; free: number | null; total: number | null }
export interface Stats {
  files: number; total_bytes: number; selected_files: number; selected_bytes: number; pending_files: number; pending_bytes: number;
  backed_files: number; backed_bytes: number; new_files: number; review_files: number; review_bytes: number; skipped_files: number; skipped_bytes: number; pc_name: string; last_backup: string | null; next_run: string | null;
  history: { day: string; bytes: number }[]; largest_files: { path: string; size: number }[];
  largest_folders: { name: string; size: number }[]; destinations: Dest[];
}
export interface Job { state: "idle" | "running" | "done" | "error" | "cancelled"; type: string; message: string; done: number; total: number; started?: number }
/** Time left, worked out from how fast the job has gone so far. */
export function eta(job: Job): string {
  if (!job.started || job.total <= 0 || job.done <= 0) return "";
  const elapsed = Date.now() / 1000 - job.started, frac = job.done / job.total;
  if (frac >= 1) return "Almost done";
  if (elapsed < 3 || frac < 0.02) return "Estimating time left...";
  const s = Math.round(elapsed * (1 - frac) / frac);
  const m = Math.round(s / 60);
  const t = s < 60 ? `${Math.max(s, 5)} seconds` : s < 3600 ? `${m} ${m === 1 ? "minute" : "minutes"}` : `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min`;
  return `${Math.round(frac * 100)}% done, about ${t} left`;
}
export interface Settings {
  sources: string[]; destinations: string[]; excludes: string[]; max_size_mb: number; versions: number; compress: boolean;
  schedule: { enabled: boolean; time: string; days: number[] }; auto_scan_minutes: number; webhook: string; whole_pc: boolean; scan_roots: string[]; skip_junk: boolean; new_files: "review" | "include"; junk_list: string[]; pc_name: string; data_dir: string; auth_required: boolean; update_check: boolean; deep_check: boolean;
}
export interface UpdateInfo { enabled: boolean; current: string; latest: string; available: boolean; can_install: boolean; page: string; notes: string; error: string }
export interface LogRow { at: string; level: "info" | "warn" | "error"; action: string; message: string }
export interface FolderRow { name: string; path: string; files: number; bytes: number; selected: number; review: number }
export interface Explore { path: string; parent: string | null; total_files: number; folders: FolderRow[]; files: FileRow[] }
export interface TypeRow { key: string; name: string; files: number; bytes: number; selected: number; review: number }
export interface BigDir { dir: string; files: number; bytes: number; selected: number; review: number }
export interface Preset { key: string; label: string; desc: string }

import { useEffect, useState } from "react";
/** useState that survives switching tabs and reloading the page (kept in this browser). */
export function useStored<T>(key: string, init: T) {
  const [v, setV] = useState<T>(() => { try { const s = localStorage.getItem("ae:" + key); return s === null ? init : (JSON.parse(s) as T); } catch { return init; } });
  useEffect(() => { try { localStorage.setItem("ae:" + key, JSON.stringify(v)); } catch { /* storage unavailable */ } }, [key, v]);
  return [v, setV] as const;
}
