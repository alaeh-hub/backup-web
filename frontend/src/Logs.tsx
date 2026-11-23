import { useCallback, useEffect, useRef, useState } from "react";
import { api, LogRow } from "./api";

export function Logs({ tick }: { tick: number }) {
  const [logs, setLogs] = useState<LogRow[]>([]); const [level, setLevel] = useState(""); const [q, setQ] = useState("");
  const qs = `level=${level}&q=${encodeURIComponent(q)}`;
  const seq = useRef(0);
  const load = useCallback(async () => { const my = ++seq.current; const r = await api<LogRow[]>("/api/logs?" + qs); if (my === seq.current) setLogs(r); }, [qs]);
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t); }, [load, tick]);
  return (
    <>
      <div className="toolbar">
        <input aria-label="Search logs" placeholder="Search the log" value={q} onChange={e => setQ(e.target.value)} />
        <select aria-label="Level" value={level} onChange={e => setLevel(e.target.value)}><option value="">All levels</option><option value="info">Info</option><option value="warn">Warnings</option><option value="error">Errors</option></select>
        <button onClick={load}>Refresh</button>
        <a className="btn" href={"/api/logs.csv?" + qs}>Export CSV</a>
      </div>
      <div className="scroll">
        <table>
          <thead><tr><th>Time</th><th>Level</th><th>Action</th><th>Details</th></tr></thead>
          <tbody>
            {logs.map((l, i) => <tr key={i}><td className="nowrap">{l.at}</td><td><span className={"tag lv-" + l.level}>{l.level}</span></td><td>{l.action}</td><td className="wrap">{l.message}</td></tr>)}
            {!logs.length && <tr><td colSpan={4} className="empty">No activity yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
