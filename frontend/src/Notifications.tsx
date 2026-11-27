import { useEffect, useRef, useState } from "react";
import { Alert, LogRow, api, useStored } from "./api";
import { Icon } from "./ui";

/** The bell: what needs attention now (a missing or full drive, no recent backup), and what went wrong lately. */
export function Notifications({ alerts, go }: { alerts: Alert[]; go: (tab: string) => void }) {
  const [open, setOpen] = useState(false);
  const [gone, setGone] = useStored<string[]>("dismissed", []);
  const [recent, setRecent] = useState<LogRow[] | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const live = alerts.filter(a => !gone.includes(a.key));
  useEffect(() => { setGone(g => g.filter(k => alerts.some(a => a.key === k))); }, [alerts.map(a => a.key).join("|")]);   // a dismissed warning that came back is shown again
  useEffect(() => {
    if (!open) return;
    let stale = false;
    Promise.all([api<LogRow[]>("/api/logs?level=error"), api<LogRow[]>("/api/logs?level=warn")])
      .then(([e, w]) => { if (!stale) setRecent([...e, ...w].sort((a, b) => (a.at < b.at ? 1 : -1)).slice(0, 6)); })
      .catch(() => { if (!stale) setRecent([]); });
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away); document.addEventListener("keydown", key);
    return () => { stale = true; document.removeEventListener("mousedown", away); document.removeEventListener("keydown", key); };
  }, [open]);
  return (
    <div className="bell" ref={box}>
      <button aria-label={live.length ? `Notifications, ${live.length} need attention` : "Notifications"} aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <Icon name="bell" />{!!live.length && <span className="badge">{live.length}</span>}
      </button>
      {open && (
        <div className="bell-panel" role="dialog" aria-label="Notifications">
          <h3>Needs attention</h3>
          {!live.length && <p className="sub">Nothing needs your attention.</p>}
          <ul className="bell-list">
            {live.map(a => (
              <li key={a.key} className={"bell-item " + a.level}>
                <b>{a.title}</b><span className="sub">{a.text}</span>
                <span className="bell-actions"><button onClick={() => { go(a.go); setOpen(false); }}>Open</button><button className="quiet" onClick={() => setGone(g => [...g, a.key])}>Dismiss</button></span>
              </li>
            ))}
          </ul>
          <h3>Recent problems</h3>
          {recent === null && <p className="sub">Loading…</p>}
          {recent && !recent.length && <p className="sub">No warnings or errors in the log.</p>}
          <ul className="bell-list">
            {recent?.map((r, i) => <li key={i} className="bell-item"><span className="sub">{r.at}</span><span>{r.message}</span></li>)}
          </ul>
          <button className="quiet" onClick={() => { go("logs"); setOpen(false); }}>Open the full log</button>
        </div>
      )}
    </div>
  );
}
