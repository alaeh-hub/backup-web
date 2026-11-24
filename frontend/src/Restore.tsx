import { useEffect, useState } from "react";
import { api, fmt, useStored, FileRow, Settings } from "./api";
import { PathPicker } from "./PathList";
import { Select } from "./Select";


export function Restore({ onJob }: { onJob: () => void }) {
  const [dests, setDests] = useState<string[]>([]); const [dest0, setDest] = useStored("restore.dest", "");
  const dest = dests.includes(dest0) ? dest0 : dests[0] ?? "";
  const [q, setQ] = useState(""); const [rows, setRows] = useState<FileRow[]>([]); const [total, setTotal] = useState(0); const [more, setMore] = useState(false);
  const [pick, setPick] = useState<Set<string>>(new Set()); const [target, setTarget] = useStored("restore.target", ""); const [overwrite, setOverwrite] = useStored("restore.overwrite", false);
  const [err, setErr] = useState("");
  useEffect(() => { api<Settings>("/api/settings").then(s => setDests(s.destinations)); }, []);
  const page = (offset: number) => api<{ rows: FileRow[]; total: number }>(`/api/files?status=has_backup&dest=${encodeURIComponent(dest)}&q=${encodeURIComponent(q)}&limit=200&offset=${offset}`);
  useEffect(() => {
    if (!dest) return;
    let stale = false;
    setPick(new Set());                                // a file picked for another drive may not exist on this one
    const t = setTimeout(async () => {
      try {
        const p = await page(0);
        if (!stale) { setRows(p.rows); setTotal(p.total); }
      } catch (e) { if (!stale) setErr((e as Error).message); }
    }, 250);
    return () => { stale = true; clearTimeout(t); };
  }, [q, dest]);
  const showMore = async () => {
    setMore(true);
    try { const p = await page(rows.length); setRows(r => [...r, ...p.rows.filter(x => !r.some(y => y.id === x.id))]); setTotal(p.total); }
    catch (e) { setErr((e as Error).message); }
    setMore(false);
  };
  const flip = (id: string) => setPick(s => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const go = async (items: { id: string; dest: string }[]) => {
    try { setErr(""); await api("/api/restore", "POST", { items, target, overwrite }); onJob(); } catch (e) { setErr((e as Error).message); }
  };
  return (
    <>
      <section className="block">
        <h2>Restore files</h2>
        <p className="sub">Pick the files, choose where to put them, then restore. Leave the folder empty to put files back where they came from. Existing files are kept unless you tick overwrite.</p>
        <label>Restore from drive
          <Select label="Restore from drive" value={dest} onChange={setDest} options={dests.map(d => ({ value: d, label: d }))} />
        </label>
        <label>Restore to folder<PathPicker value={target} onChange={setTarget} /></label>
        <label className="check"><input type="checkbox" checked={overwrite} onChange={e => setOverwrite(e.target.checked)} /> Overwrite files that already exist</label>
        {err && <p className="err">{err}</p>}
        <div><button className="primary" disabled={!pick.size || !dest} onClick={() => go([...pick].map(id => ({ id, dest })))}>Restore {pick.size} selected</button></div>
      </section>
      <div className="toolbar"><input aria-label="Search backed up files" placeholder="Search backed up files" value={q} onChange={e => setQ(e.target.value)} /><span className="sub">{total.toLocaleString()} files with a backup on this drive</span></div>
      <ul className="rows">
        {rows.map(f => (
          <li key={f.id}>
            <div className="line">
              <label className="check"><input type="checkbox" checked={pick.has(f.id)} onChange={() => flip(f.id)} aria-label={"Select " + f.path} /></label>
              <span className="path" title={f.path}><bdi>{f.path}</bdi></span><span className="sub">{fmt(f.size)}</span>
            </div>
          </li>
        ))}
      </ul>
      {rows.length < total && <div><button onClick={showMore} disabled={more}>{more ? "Loading..." : `Show more (${(total - rows.length).toLocaleString()} more)`}</button></div>}
    </>
  );
}
