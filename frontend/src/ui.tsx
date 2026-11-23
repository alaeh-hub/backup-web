import { useEffect, useLayoutEffect, useRef } from "react";
import { animate, stagger } from "animejs";

export const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

const P: Record<string, string> = {
  overview: "M4 13h4v7H4zM10 4h4v16h-4zM16 9h4v11h-4z",
  inbox: "M4 13l2.5-7h11L20 13v6H4zM4 13h5l1 2h4l1-2h5",
  check: "M5 12.5l4.5 4.5L19 7.5",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  restore: "M4 12a8 8 0 1 0 3-6.2M4 4v4.5h4.5M12 8v4.5l3 1.5",
  organize: "M4 5h16M4 12h10M4 19h6M17 15l3 3-3 3",
  log: "M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h7",
  settings: "M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zM12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1",
  scan: "M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M4 12h16",
  backup: "M12 16V5M7.5 9.5L12 5l4.5 4.5M5 15v3a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3",
  file: "M6 3h8l4 4v14H6zM14 3v4h4",
  cancel: "M6 6l12 12M18 6L6 18",
  drive: "M4 14l2-8h12l2 8M4 14v4h16v-4M4 14h16M16.5 16.5h.01",
  chevron: "M6 9l6 6 6-6",
};

/** A small outlined icon, drawn inline so it follows the text colour. */
export function Icon({ name, className = "ico" }: { name: string; className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={P[name] ?? P.file} />
    </svg>
  );
}

/** Children rise in one after another when a screen opens (anime.js). */
export function Page({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || reduced()) return;
    const a = animate(Array.from(el.children), { opacity: [0, 1], translateY: [14, 0], delay: stagger(55), duration: 520, ease: "outExpo" });
    return () => { a.revert(); };
  }, []);
  return <div className="page" ref={ref}>{children}</div>;
}

/** A figure that counts up to its value (anime.js), then shows it exactly. */
export function CountUp({ value, format, className }: { value: number; format: (n: number) => string; className?: string }) {
  const ref = useRef<HTMLElement>(null);
  const from = useRef(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (reduced()) { el.textContent = format(value); from.current = value; return; }
    const o = { v: from.current };
    const a = animate(o, { v: value, duration: 1100, ease: "outExpo", onUpdate: () => { el.textContent = format(o.v); }, onComplete: () => { el.textContent = format(value); } });
    from.current = value;
    return () => { a.pause(); from.current = o.v; };
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  return <strong ref={ref} className={className}>{format(value)}</strong>;
}

/** Grows the matching children of a container from zero when it appears (anime.js). */
export function useGrow(selector: string, axis: "x" | "y", deps: unknown[]) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || reduced()) return;
    const items = el.querySelectorAll(selector);
    if (!items.length) return;
    const a = animate(items, { [axis === "x" ? "scaleX" : "scaleY"]: [0, 1], delay: stagger(70, { start: 150 }), duration: 900, ease: "outExpo" });
    return () => { a.revert(); };
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  return ref;
}
