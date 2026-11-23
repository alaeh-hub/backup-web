import { useState } from "react";
import { api, fmt } from "./api";

interface Browse { path: string; parent: string | null; dirs: string[] }
interface Drive { path: string; free?: number; total?: number }
const join = (a: string, b: string) => a.replace(/[\\/]+$/, "") + (a.includes("\\") ? "\\" : "/") + b;

/** A folder field with a drive and folder browser. */
export function PathPicker({ value, onChange, onUse, useLabel }: { value: string; onChange: (v: string) => void; onUse?: (v: string) => void; useLabel?: string }) {
  const [open, setOpen] = useState(false);
  const [br, setBr] = useState<Browse | null>(null);
  const [drives, setDrives] = useState<Drive[]>([]);
  const [err, setErr] = useState("");
  const go = async (p: string) => { try { setErr(""); setBr(await api<Browse>("/api/browse?path=" + encodeURIComponent(p))); } catch (e) { setErr((e as Error).message); } };
  const toggle = async () => {
    if (open) return setOpen(false);
    setOpen(true); setBr(null);
    try { setErr(""); setDrives(await api<Drive[]>("/api/drives")); } catch (e) { setErr((e as Error).message); }
  };
  return (
    <div className="picker">
      <div className="row">
        <input aria-label="Folder path" value={value} onChange={e => onChange(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && onUse && value.trim()) onUse(value.trim()); }} placeholder="Type a folder path" />
        <button type="button" onClick={toggle}>{open ? "Close" : "Browse"}</button>
        {onUse && <button type="button" onClick={() => value.trim() && onUse(value.trim())}>{useLabel ?? "Add"}</button>}
      </div>
      {open && (
        <div className="browser">
          {err && <p className="err">{err}</p>}
          <div className="row">
            <button type="button" onClick={() => setBr(null)}>Drives</button>
            {br?.parent && <button type="button" onClick={() => go(br.parent!)}>Up</button>}
            {br && <button type="button" className="primary" onClick={() => { if (onUse) onUse(br.path); else onChange(br.path); setOpen(false); }}>{onUse ? (useLabel ?? "Add this folder") : "Use this folder"}</button>}
          </div>
          {br && <p className="sub">{br.path}</p>}
          <ul className="dirs">
            {!br && drives.map(d => <li key={d.path}><button type="button" onClick={() => go(d.path)}>{d.path}{d.total ? ` (${fmt(d.free)} free of ${fmt(d.total)})` : ""}</button></li>)}
            {br?.dirs.map(d => <li key={d}><button type="button" onClick={() => go(join(br.path, d))}>{d}</button></li>)}
            {br && !br.dirs.length && <li className="sub">No subfolders</li>}
          </ul>
        </div>
      )}
    </div>
  );
}

export function PathList({ title, hint, items, onChange }: { title: string; hint: string; items: string[]; onChange: (v: string[]) => void }) {
  const [v, setV] = useState("");
  return (
    <section className="block">
      <h2>{title}</h2>
      <p className="sub">{hint}</p>
      <ul className="rows">
        {items.map(p => <li key={p} className="line"><span className="path" title={p}><bdi>{p}</bdi></span><button type="button" onClick={() => onChange(items.filter(x => x !== p))}>Remove</button></li>)}
        {!items.length && <li className="sub">None yet</li>}
      </ul>
      <PathPicker value={v} onChange={setV} onUse={p => { if (!items.includes(p)) onChange([...items, p]); setV(""); }} />
    </section>
  );
}
