import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { api } from "./api";
import { Icon } from "./ui";

export interface NameResult { name: string; folder: string; renamed: string[]; pending: string[] }
interface Preview { ok: boolean; name?: string; folder?: string; taken?: boolean; error?: string }

const MAX = 40;
const IDEAS = ["Office PC", "Warehouse", "Shop counter", "Accounting"];

/** One sentence for the app's message line after a name was saved. */
export function namedMessage(r: NameResult, first: boolean): string {
  if (first) return `Welcome. This PC is called ${r.name}.`;
  if (r.pending.length) return `Renamed to ${r.name}. The folder on the drive keeps its old name until the drive is connected and a backup starts, and backups work the same meanwhile.`;
  if (r.renamed.length) return `Renamed to ${r.name}. Its folder on the backup drive was renamed too.`;
  return `Renamed to ${r.name}. Its folder on the backup drive is created with this name at the first backup.`;
}

/**
 * Asks for this PC’s name: once on a new install, and again from Settings to rename it. The name is the PC’s folder on the
 * backup drive, so the page shows that folder as it is typed (the server tidies the name, so what is shown is what is made).
 */
export function NamePc({ mode, current, drive, onDone, onCancel }: {
  mode: "first" | "rename"; current: string; drive?: string; onDone: (r: NameResult) => void; onCancel: () => void;
}) {
  const first = mode === "first";
  const [value, setValue] = useState(first ? "" : current);
  const [prev, setPrev] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const seq = useRef(0); const box = useRef<HTMLFormElement>(null); const field = useRef<HTMLInputElement>(null); const from = useRef<HTMLElement | null>(null);
  const trimmed = value.replace(/\s+/g, " ").trim();
  const same = !first && trimmed === current;

  useEffect(() => {
    from.current = document.activeElement as HTMLElement | null;
    field.current?.focus();
    return () => { from.current?.focus?.(); };
  }, []);

  useEffect(() => {                                                   // what the name becomes on the drive, a moment after typing stops
    setErr("");
    if (!trimmed) { setPrev(null); return; }
    const id = ++seq.current;
    const t = window.setTimeout(() => {
      api<Preview>("/api/pc/preview?name=" + encodeURIComponent(trimmed)).then(p => { if (id === seq.current) setPrev(p); }).catch(() => undefined);
    }, 160);
    return () => window.clearTimeout(t);
  }, [trimmed]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !first) { e.preventDefault(); onCancel(); }
      else if (e.key === "Tab") {                                      // keep the focus inside the dialog
        const items = Array.from(box.current?.querySelectorAll<HTMLElement>("input, button:not(:disabled)") ?? []);
        if (!items.length) return;
        const a = items[0], z = items[items.length - 1];
        if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
        else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [first, onCancel]);

  const save = async (name: string) => {
    if (busy) return;
    setBusy(true); setErr("");
    try { onDone(await api<NameResult>("/api/pc/name", "POST", { name })); }
    catch (e) { setErr((e as Error).message); setBusy(false); }
  };
  const ok = !!prev?.ok && prev.name === trimmed && !same && !busy;
  const folder = prev?.ok ? prev.folder : "";
  const path = (drive ? drive.replace(/[\\/]+$/, "") + "\\" : "") + (folder || "");

  return (
    <motion.div className="dialog-back" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}
      onPointerDown={e => { if (!first && e.target === e.currentTarget) onCancel(); }}>
      <motion.form ref={box} className="name-dialog" role="dialog" aria-modal="true" aria-labelledby="name-title" aria-describedby="name-lead" noValidate
        initial={{ opacity: 0, y: 18, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 10, scale: 0.98 }} transition={{ type: "spring", stiffness: 480, damping: 36 }}
        onSubmit={e => { e.preventDefault(); if (ok) void save(trimmed); }}>
        <img className="logo name-logo" src="/static/ala-eh-logo.png" alt="" width={44} height={44} />

        <div className="name-head">
          <h2 id="name-title">{first ? "What should we call this PC?" : "Give this PC a new name"}</h2>
          <p id="name-lead">{first
            ? "Pick a name you will recognise. It labels this PC’s backups and becomes its own folder on the backup drive."
            : "The folder on the backup drive is renamed to match. Your backed up files stay exactly where they are."}</p>
        </div>

        <div className="name-field">
          <div className="name-field-top">
            <label htmlFor="pc-name">PC name</label>
            <span className={"name-count" + (value.length >= MAX - 5 ? " near" : "")} aria-live="polite">{value.length} of {MAX}</span>
          </div>
          <div className="name-line">
            <input id="pc-name" ref={field} className="name-input" type="text" inputMode="text" autoComplete="off" spellCheck={false} maxLength={MAX}
              placeholder={first ? "For example, Front desk laptop" : current} value={value} aria-invalid={!!(trimmed && prev && !prev.ok)} aria-describedby="name-path name-note"
              onChange={e => setValue(e.target.value)} />
          </div>
        </div>

        <div id="name-path" className={"name-path" + (folder ? "" : " empty")}>
          <Icon name="drive" />
          <span className="name-path-text">
            <span className="k">Folder on the backup drive</span>
            <b key={path || "empty"} className="name-path-folder"><bdi>{folder ? path : "Appears as you type"}</bdi></b>
          </span>
        </div>

        <div id="name-note" className="name-note" aria-live="polite">
          {err ? <p className="err">{err}</p>
            : trimmed && prev && !prev.ok ? <p className="err">{prev.error}</p>
            : prev?.ok && prev.taken ? <p className="warn">Another PC on the drive already uses this name, so a short number is added to this PC’s folder.</p>
            : same ? <p className="sub">That is the name it has now.</p> : null}
        </div>

        <div className="name-ideas" role="group" aria-label="Name ideas">
          {IDEAS.map(i => <button key={i} type="button" className={trimmed === i ? "on" : ""} onClick={() => { setValue(i); field.current?.focus(); }}>{i}</button>)}
        </div>

        <div className="dialog-actions name-actions">
          {!first && <button type="button" disabled={busy} onClick={onCancel}>Cancel</button>}
          <button type="submit" className="primary" disabled={!ok}>{busy ? "Saving..." : first ? "Continue" : "Save name"}</button>
        </div>
      </motion.form>
    </motion.div>
  );
}
