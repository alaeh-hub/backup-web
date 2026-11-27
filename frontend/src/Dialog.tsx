import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";

interface Req { message: string; ok: string; cancel: string | null; resolve: (v: boolean) => void }
let push: ((r: Req) => void) | null = null;

/** Ask a yes or no question in the app's own dialog (falls back to the browser's if the host is not mounted). */
export function ask(message: string, ok = "Continue"): Promise<boolean> {
  return new Promise(res => (push ? push({ message, ok, cancel: "Cancel", resolve: res }) : res(window.confirm(message))));
}

/** Show a message that needs one click. */
export function tell(message: string): Promise<void> {
  return new Promise(res => { if (push) push({ message, ok: "OK", cancel: null, resolve: () => res() }); else { window.alert(message); res(); } });
}

export function DialogHost() {
  const [req, setReq] = useState<Req | null>(null);
  const reqRef = useRef<Req | null>(null); const from = useRef<HTMLElement | null>(null);
  const box = useRef<HTMLDivElement>(null); const okBtn = useRef<HTMLButtonElement>(null);
  reqRef.current = req;
  useEffect(() => { push = r => { from.current = document.activeElement as HTMLElement | null; setReq(r); }; return () => { push = null; }; }, []);
  const close = (v: boolean) => { reqRef.current?.resolve(v); setReq(null); from.current?.focus?.(); };

  useEffect(() => {
    if (!req) return;
    okBtn.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); close(false); }
      else if (reqRef.current?.cancel && !e.ctrlKey && !e.metaKey && !e.altKey && (e.key === "y" || e.key === "Y")) { e.preventDefault(); close(true); }       // Y is yes
      else if (reqRef.current?.cancel && !e.ctrlKey && !e.metaKey && !e.altKey && (e.key === "n" || e.key === "N")) { e.preventDefault(); close(false); }      // N is no
      else if (e.key === "Tab") {                                   // keep the focus inside the dialog
        const items = Array.from(box.current?.querySelectorAll<HTMLElement>("button") ?? []);
        if (!items.length) return;
        const first = items[0], last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [req]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <AnimatePresence>
      {req && (
        <motion.div className="dialog-back" key="back" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }} onPointerDown={e => { if (e.target === e.currentTarget) close(false); }}>
          <motion.div ref={box} className="dialog" role="alertdialog" aria-modal="true" aria-describedby="dialog-text"
            initial={{ opacity: 0, y: 14, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8, scale: 0.98 }} transition={{ type: "spring", stiffness: 520, damping: 38 }}>
            <p id="dialog-text">{req.message}</p>
            <div className="dialog-actions">
              {req.cancel && <button onClick={() => close(false)}>{req.cancel}</button>}
              <button ref={okBtn} className="primary" onClick={() => close(true)}>{req.ok}</button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
