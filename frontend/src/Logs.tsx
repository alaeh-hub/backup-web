import { useCallback, useEffect, useRef, useState } from "react";
import { api, LogRow } from "./api";
import { Cluster, Group } from "./Panel";
import { SearchBox } from "./SearchBox";
import { searchHelp } from "./smart";
import { Select } from "./Select";

export function Logs({ tick }: { tick: number }) {
  const [logs, setLogs] = useState<LogRow[]>([]); const [level, setLevel] = useState(""); const [q, setQ] = useState("");
  const qs = `level=${level}&q=${encodeURIComponent(q)}`;
  const seq = useRef(0);
  const load = useCallback(async () => { const my = ++seq.current; const r = await api<LogRow[]>("/api/logs?" + qs); if (my === seq.current) setLogs(r); }, [qs]);
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t); }, [load, tick]);
  return (
    <Group title="Logs" lead="Everything the tool has done, newest first.">
      <Cluster>
      <div className="toolbar">
        <SearchBox saveKey="logs" label="Search logs" placeholder="Search the log: words, level:error, -word" value={q} onChange={setQ} help={searchHelp + " level:error shows only errors."} />
        <Select label="Level" value={level} onChange={setLevel} options={[{ value: "", label: "All levels" }, { value: "info", label: "Info" }, { value: "warn", label: "Warnings" }, { value: "error", label: "Errors" }]} />
        <button onClick={load}>Refresh</button>
        <a className="btn" href={"/api/logs.csv?" + qs}>Export CSV</a>
      </div>
      <div className="scroll">
        <table className="logtable">
          <thead><tr><th>Time</th><th>Level</th><th>Action</th><th>Details</th></tr></thead>
          <tbody>
            {logs.map((l, i) => <tr key={i}><td className="nowrap">{l.at}</td><td><span className={"tag lv-" + l.level}>{l.level}</span></td><td>{l.action}</td><td className="wrap">{l.message}</td></tr>)}
            {!logs.length && <tr><td colSpan={4} className="empty">No activity yet.</td></tr>}
          </tbody>
        </table>
      </div>
      </Cluster>
    </Group>
  );
}
