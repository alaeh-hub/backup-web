import { useState } from "react";
import { api, fmt } from "./api";
import { AddedMark } from "./ui";

interface Browse { path: string; parent: string | null; dirs: string[] }
interface Drive { path: string; free?: number; total?: number }
const join = (a: string, b: string) => a.replace(/[\\/]+$/, "") + (a.includes("\\") ? "\\" : "/") + b;

const key = (p: string) => p.replace(/[\\/]+$/, "").replace(/\//g, "\\").toLowerCase();

/** A folder field with a drive and folder browser. `added` lists the folders already in the list this picker feeds, so the
 *  browser can show which ones they are (and which sit inside one) instead of letting them be added twice. */
export function PathPicker({ value, onChange, onUse, useLabel, added = [] }: { value: string; onChange: (v: string) => void; onUse?: (v: string) => void; useLabel?: string; added?: string[] }) {
  const exact = (p: string) => added.some(a => key(a) === key(p));
  const inside = (p: string) => added.some(a => key(p).startsWith(key(a) + "\\"));
  const holds = (p: string) => added.some(a => key(a).startsWith(key(p) + "\\"));
  const typed = value.trim();
  const note = !typed ? "" : exact(typed) ? "This folder is already added." : inside(typed) ? "This folder is inside one that is already added, so it is covered." : "";
  const [open, setOpen] = useState(false);
  const [br, setBr] = useState<Browse | null>(null);
  const [drives, setDrives] = useState<Drive[]>([]);
  const [err, setErr] = useState("");
  const go = async (p: string) => {
    try { setErr(""); setBr(await api<Browse>("/api/browse?path=" + encodeURIComponent(p))); requestAnimationFrame(() => document.querySelector<HTMLElement>(".browser .dirs button")?.focus()); }       // the first folder is ready for the arrow keys
    catch (e) { setErr((e as Error).message); }
  };
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
        {onUse && <button type="button" disabled={exact(typed)} onClick={() => typed && onUse(typed)}>{exact(typed) ? "Added" : useLabel ?? "Add"}</button>}
      </div>
      {note && <p className="sub pick-note" role="status">{note}</p>}
      {open && (
        <div className="browser" onKeyDown={e => {
          const t = e.target as HTMLElement;
          if (t.tagName === "INPUT") return;
          const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>(".dirs button")), at = items.indexOf(t);
          if (e.key === "ArrowDown") { e.preventDefault(); items[Math.min(at + 1, items.length - 1)]?.focus(); }
          else if (e.key === "ArrowUp") { e.preventDefault(); items[Math.max(at - 1, 0)]?.focus(); }
          else if (e.key === "ArrowRight" && at >= 0) { e.preventDefault(); items[at].click(); }
          else if ((e.key === "ArrowLeft" || e.key === "Backspace") && br?.parent) { e.preventDefault(); void go(br.parent); }
          else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setOpen(false); }
        }}>
          {err && <p className="err">{err}</p>}
          <div className="row">
            <button type="button" onClick={() => setBr(null)}>Drives</button>
            {br?.parent && <button type="button" onClick={() => go(br.parent!)}>Up</button>}
            {br && <button type="button" className="primary" disabled={!!onUse && exact(br.path)} onClick={() => { if (onUse) onUse(br.path); else onChange(br.path); setOpen(false); }}>{onUse ? (exact(br.path) ? "Already added" : useLabel ?? "Add this folder") : "Use this folder"}</button>}
          </div>
          {br && <p className="sub">{br.path}{exact(br.path) ? " is already added." : inside(br.path) ? " is inside a folder that is already added." : ""}</p>}
          <ul className="dirs">
            {!br && drives.map(d => <li key={d.path}><button type="button" className={exact(d.path) ? "is-added" : ""} onClick={() => go(d.path)}>{exact(d.path) && <AddedMark />}<span>{d.path}{d.total ? ` (${fmt(d.free)} free of ${fmt(d.total)})` : ""}</span>{exact(d.path) ? <span className="added-text">Added</span> : holds(d.path) && <span className="sub">has an added folder</span>}</button></li>)}
            {br?.dirs.map(d => { const full = join(br.path, d), on = exact(full); return <li key={d}><button type="button" className={on ? "is-added" : ""} onClick={() => go(full)}>{on && <AddedMark />}<span>{d}</span>{on ? <span className="added-text">Added</span> : holds(full) && <span className="sub">has an added folder</span>}</button></li>; })}
            {br && !br.dirs.length && <li className="sub">No subfolders</li>}
          </ul>
        </div>
      )}
    </div>
  );
}

export function PathList({ title, hint, items, onChange, bare }: { title: string; hint: string; items: string[]; onChange: (v: string[]) => void; bare?: boolean }) {
  const [v, setV] = useState("");
  const Wrap = bare ? "div" : "section";             // bare: the caller already shows the title and the hint
  return (
    <Wrap className={bare ? "plist" : "block"}>
      {!bare && <h2>{title}</h2>}
      {!bare && <p className="sub">{hint}</p>}
      <ul className="rows" aria-label={title}>
        {items.map(p => <li key={p} className="line added"><AddedMark /><span className="path" title={p}><bdi>{p}</bdi></span><span className="added-text">Added</span><button type="button" onClick={() => onChange(items.filter(x => x !== p))}>Remove</button></li>)}
        {!items.length && <li className="sub">None yet</li>}
      </ul>
      <PathPicker value={v} onChange={setV} added={items} onUse={p => { if (!items.includes(p)) onChange([...items, p]); setV(""); }} />
    </Wrap>
  );
}
