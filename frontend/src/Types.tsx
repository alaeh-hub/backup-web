import { useCallback, useEffect, useState } from "react";
import { api, fmt, TypeRow } from "./api";

export function Types({ onChange }: { onChange: () => void }) {
  const [rows, setRows] = useState<TypeRow[]>([]); const [err, setErr] = useState("");
  const load = useCallback(async () => { try { setErr(""); setRows(await api<TypeRow[]>("/api/types")); } catch (e) { setErr((e as Error).message); } }, []);
  useEffect(() => { load(); }, [load]);
  const toggle = async (t: TypeRow) => {
    const on = t.selected < t.files;
    setRows(rs => rs.map(x => x.key === t.key ? { ...x, selected: on ? x.files : 0, review: 0 } : x));
    try { await api("/api/files/select", "POST", { selected: on, filter: { cat: t.key } }); onChange(); } catch { await load(); }
  };
  if (err) return <p className="err">Could not load the file types: {err}</p>;
  const max = Math.max(...rows.map(r => r.bytes), 1);
  return (
    <>
      <p className="sub">Switch a whole kind of file on or off. The size shows how much space each kind takes.</p>
      <ul className="rows">
        {rows.map(t => (
          <li key={t.key} className="line">
            <label className="switch"><input type="checkbox" checked={t.selected === t.files} onChange={() => toggle(t)} aria-label={"Back up " + t.name} /><span /></label>
            <span className="grow">{t.name}<span className="meter slim"><i style={{ transform: `scaleX(${t.bytes / max})` }} /></span></span>
            <span className="sub">{t.files.toLocaleString()} files{t.review ? `, ${t.review.toLocaleString()} to review` : ""}{t.selected && t.selected < t.files ? `, ${t.selected.toLocaleString()} chosen for backup` : ""}</span>
            <strong>{fmt(t.bytes)}</strong>
          </li>
        ))}
        {!rows.length && <li className="sub">No files yet. Click “Scan files” first.</li>}
      </ul>
    </>
  );
}
