import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Icon } from "./ui";

/** A key cap. */
export const Kbd = ({ children }: { children: React.ReactNode }) => <kbd className="kbd">{children}</kbd>;

type Row = [keys: string[], what: string];
export const GROUPS: { title: string; rows: Row[] }[] = [
  { title: "Everywhere", rows: [
    [["?"], "Show this list"], [["1", "to", "0"], "Go to a screen by its number"], [["g", "then", "o"], "Go to a screen by letter: o Overview, n New files, s Selected, f Files, r Restore, d Devices, z Organize, l Logs, t Settings, p Other PCs"],
    [["Alt", "←"], "Back to the previous screen (also the mouse back button)"], [["Alt", "→"], "Forward again (also the mouse forward button)"],
    [["/"], "Search this screen (Ctrl+K works too)"], [["Ctrl", "Enter"], "Back up now"], [["Ctrl", "Shift", "S"], "Scan files"], [["r"], "Refresh this screen"], [["t"], "Light or dark mode"], [["Esc"], "Close, clear or step back"],
  ] },
  { title: "Lists of files and folders", rows: [
    [["j"], "Next row (↓ from the search box too)"], [["k"], "Previous row"], [["Home"], "First row"], [["End"], "Last row"],
    [["Enter"], "Open the preview, or open the folder"], [["x"], "Choose or skip the row"], [["Esc"], "Leave the list"],
  ] },
  { title: "Preview window", rows: [
    [["←"], "Previous file (also the mouse back button)"], [["→"], "Next file (also the mouse forward button)"], [["Home"], "First file"], [["End"], "Last file"],
    [["Enter"], "Back up this file and go to the next"], [["b"], "Back up this file"], [["s"], "Skip this file and go to the next"],
    [["↑", "↓"], "Scroll"], [["PgUp", "PgDn"], "Scroll a page"], [["Space"], "Scroll a page, or play and pause"],
    [["f"], "Full screen"], [["i"], "Show or hide the details"], [["c"], "Copy the path"], [["Esc"], "Close (also a middle click)"],
    [["+", "-", "0"], "Zoom a picture in, out, back (Ctrl and the wheel too)"], [["r"], "Turn a picture a quarter turn"], [["Double click"], "Full screen"],
  ] },
  { title: "Audio and video", rows: [
    [["Space"], "Play or pause (k too)"], [["j"], "Back 10 seconds"], [["l"], "Forward 10 seconds"], [["Shift", "←"], "Back 5 seconds"], [["Shift", "→"], "Forward 5 seconds"],
    [["↑", "↓"], "Volume"], [["m"], "Mute"], [["[", "]"], "Slower, faster"], [["0", "to", "9"], "Jump to 0% to 90% of the file"],
  ] },
  { title: "Dialogs, menus and folder browser", rows: [
    [["Enter"], "Confirm"], [["y"], "Yes"], [["n"], "No"], [["Esc"], "Cancel"],
    [["↑", "↓"], "Move in a menu or the folder browser"], [["Enter"], "Open the folder, or pick the menu item"], [["Backspace"], "Up one folder"],
    [["[", "]"], "Previous or next section in Settings and Other PCs"],
  ] },
];

/** The list of every shortcut. Opens with ? or F1 (or from the header), closes with Esc, ? or a click outside. */
export function ShortcutsHost() {
  const [open, setOpen] = useState(false); const calm = useReducedMotion();
  const box = useRef<HTMLDivElement>(null); const from = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const toggle = () => setOpen(o => !o);
    window.addEventListener("shortcuts", toggle);
    return () => window.removeEventListener("shortcuts", toggle);
  }, []);
  useEffect(() => {
    if (!open) return;
    from.current = document.activeElement as HTMLElement | null;
    box.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape" || e.key === "?" || e.key === "F1") { e.preventDefault(); e.stopPropagation(); setOpen(false); }
    };
    window.addEventListener("keydown", key, true);
    return () => { window.removeEventListener("keydown", key, true); from.current?.focus?.(); };
  }, [open]);
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="kb-back" key="kb" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: calm ? 0 : 0.14 }} onPointerDown={e => { if (e.target === e.currentTarget) setOpen(false); }}>
          <motion.div ref={box} tabIndex={-1} className="kb" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts"
            initial={calm ? false : { opacity: 0, y: 18, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={calm ? { opacity: 0 } : { opacity: 0, y: 10 }} transition={calm ? { duration: 0 } : { type: "spring", stiffness: 460, damping: 38 }}>
            <header className="kb-head"><h2>Keyboard shortcuts</h2><button type="button" onClick={() => setOpen(false)} aria-label="Close the list" title="Close (Esc)"><Icon name="cancel" /></button></header>
            <div className="kb-body">
              {GROUPS.map(g => (
                <section key={g.title} className="kb-group">
                  <h3>{g.title}</h3>
                  <dl>{g.rows.map(([keys, what], i) => (
                    <div key={i}>
                      <dt>{keys.map((k, j) => (k === "to" || k === "then" ? <span key={j} className="kb-sep">{k}</span> : <Kbd key={j}>{k}</Kbd>))}</dt>
                      <dd>{what}</dd>
                    </div>
                  ))}</dl>
                </section>
              ))}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export const openShortcuts = () => window.dispatchEvent(new Event("shortcuts"));
