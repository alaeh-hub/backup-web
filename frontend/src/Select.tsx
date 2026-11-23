import { useEffect, useId, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Icon } from "./ui";

export interface Opt { value: string; label: string }

/** A drop-down that looks like the rest of the app: keyboard friendly, opens up when there is no room below. */
export function Select({ value, onChange, options, label, className = "" }: { value: string; onChange: (v: string) => void; options: Opt[]; label?: string; className?: string }) {
  const [open, setOpen] = useState(false); const [active, setActive] = useState(0); const [up, setUp] = useState(false); const [end, setEnd] = useState(false);
  const root = useRef<HTMLDivElement>(null); const btn = useRef<HTMLButtonElement>(null); const list = useRef<HTMLUListElement>(null);
  const typed = useRef({ text: "", at: 0 });
  const id = useId();
  const idx = Math.max(0, options.findIndex(o => o.value === value));
  const cur = options[idx];

  const openIt = () => {
    const r = btn.current?.getBoundingClientRect();
    setUp(!!r && r.bottom + 280 > window.innerHeight && r.top > 280);
    setEnd(!!r && r.left + r.width / 2 > window.innerWidth / 2);
    setActive(idx); setOpen(true);
  };
  const pick = (i: number) => { const o = options[i]; if (o) onChange(o.value); setOpen(false); btn.current?.focus(); };

  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", down);
    return () => document.removeEventListener("pointerdown", down);
  }, [open]);
  useEffect(() => { if (open) list.current?.querySelector<HTMLElement>('[data-active="true"]')?.scrollIntoView({ block: "nearest" }); }, [open, active]);

  const onKey = (e: React.KeyboardEvent) => {
    const k = e.key;
    if (!open) { if (k === "ArrowDown" || k === "ArrowUp" || k === "Enter" || k === " ") { e.preventDefault(); openIt(); } return; }
    if (k === "ArrowDown") { e.preventDefault(); setActive(a => Math.min(a + 1, options.length - 1)); }
    else if (k === "ArrowUp") { e.preventDefault(); setActive(a => Math.max(a - 1, 0)); }
    else if (k === "Home") { e.preventDefault(); setActive(0); }
    else if (k === "End") { e.preventDefault(); setActive(options.length - 1); }
    else if (k === "Enter" || k === " ") { e.preventDefault(); pick(active); }
    else if (k === "Escape") { e.preventDefault(); setOpen(false); }
    else if (k === "Tab") setOpen(false);
    else if (k.length === 1 && !e.ctrlKey && !e.metaKey) {           // type the first letters to jump
      const t = typed.current, now = Date.now();
      t.text = now - t.at > 700 ? k.toLowerCase() : t.text + k.toLowerCase(); t.at = now;
      const hit = options.findIndex(o => o.label.toLowerCase().startsWith(t.text));
      if (hit >= 0) setActive(hit);
    }
  };

  return (
    <div className={"sel " + className} ref={root}>
      <button type="button" ref={btn} className="sel-btn" role="combobox" aria-haspopup="listbox" aria-expanded={open} aria-controls={id} aria-label={label}
        aria-activedescendant={open ? `${id}-${active}` : undefined} onClick={() => (open ? setOpen(false) : openIt())} onKeyDown={onKey}>
        <span className="sel-val">{cur?.label ?? ""}</span>
        <Icon name="chevron" className={"ico sel-chev" + (open ? " open" : "")} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.ul key="list" ref={list} id={id} role="listbox" aria-label={label} className={"sel-list" + (up ? " up" : "") + (end ? " end" : "")}
            initial={{ opacity: 0, y: up ? 6 : -6, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: up ? 4 : -4, scale: 0.98 }}
            transition={{ duration: 0.14, ease: [0.16, 1, 0.3, 1] }}>
            {options.map((o, i) => (
              <li key={o.value} id={`${id}-${i}`} role="option" aria-selected={o.value === value} data-active={i === active}
                onMouseDown={e => e.preventDefault()} onMouseMove={() => setActive(i)} onClick={() => pick(i)}>
                <span>{o.label}</span>{o.value === value && <Icon name="check" className="ico" />}
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}

const two = (n: number) => String(n).padStart(2, "0");
const HOURS: Opt[] = Array.from({ length: 24 }, (_, i) => ({ value: two(i), label: two(i) }));
const MINUTES: Opt[] = Array.from({ length: 60 }, (_, i) => ({ value: two(i), label: two(i) }));

/** A 24 hour time of day, chosen with two drop-downs instead of the browser's own picker. */
export function TimeField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [h, m] = /^\d\d:\d\d$/.test(value) ? value.split(":") : ["22", "00"];
  return (
    <div className="time">
      <Select label="Hour" value={h} options={HOURS} onChange={v => onChange(`${v}:${m}`)} />
      <span aria-hidden="true">:</span>
      <Select label="Minute" value={m} options={MINUTES} onChange={v => onChange(`${h}:${v}`)} />
    </div>
  );
}
