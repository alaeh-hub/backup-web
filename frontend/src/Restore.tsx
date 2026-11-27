import { useEffect, useState } from "react";
import { api, fmt, useStored, FileRow, Settings } from "./api";
import { Cluster, Group, Row, Switch } from "./Panel";
import { PathPicker } from "./PathList";
import { PreviewButton } from "./Preview";
import { SearchBox } from "./SearchBox";
import { Select } from "./Select";


interface Version { dest: string; version: string; size: number; at: string }

export function Restore({ onJob }: { onJob: () => void }) {
  const [dests, setDests] = useState<string[]>([]); const [dest0, setDest] = useStored("restore.dest", "");
  const dest = dests.includes(dest0) ? dest0 : dests[0] ?? "";
  const [q, setQ] = useState(""); const [rows, setRows] = useState<FileRow[]>([]); const [total, setTotal] = useState(0); const [more, setMore] = useState(false);
  const [pick, setPick] = useState<Set<string>>(new Set()); const [target, setTarget] = useStored("restore.target", ""); const [overwrite, setOverwrite] = useStored("restore.overwrite", false);
  const [err, setErr] = useState("");
  const [openV, setOpenV] = useState<string | null>(null); const [vers, setVers] = useState<Record<string, Version[] | "busy">>({});
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
  const [keepsVersions, setKeeps] = useState(false);
  useEffect(() => { api<Settings>("/api/settings").then(s => setKeeps(s.keep_versions > 0)).catch(() => undefined); }, []);
  const flip = (id: string) => setPick(s => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const go = async (items: { id: string; dest: string; version?: string }[]) => {
    try { setErr(""); await api("/api/restore", "POST", { items, target, overwrite }); onJob(); } catch (e) { setErr((e as Error).message); }
  };
  const showVersions = async (id: string) => {
    if (openV === id) return setOpenV(null);
    setOpenV(id);
    if (vers[id] && vers[id] !== "busy") return;
    setVers(v => ({ ...v, [id]: "busy" }));
    try { const r = await api<Version[]>(`/api/files/${id}/versions`); setVers(v => ({ ...v, [id]: r.filter(x => x.dest === dest) })); }
    catch (e) { setErr((e as Error).message); setVers(v => ({ ...v, [id]: [] })); }
  };
  return (
    <Group title="Restore files" lead="Pick the files, choose where to put them, then restore. Existing files are kept unless you turn on overwrite.">
      <Cluster title="Where from and where to">
        <Row title="Restore from drive" desc="Only files with a backup on this drive are listed.">
          <Select label="Restore from drive" value={dest} onChange={setDest} options={dests.map(d => ({ value: d, label: d }))} />
        </Row>
        <Row wide title="Restore to folder" desc="Leave empty to put files back where they came from.">
          <PathPicker value={target} onChange={setTarget} />
        </Row>
        <Row title="Overwrite files that already exist" desc="Off keeps the file that is on this PC now.">
          <Switch checked={overwrite} onChange={setOverwrite} label="Overwrite files that already exist" />
        </Row>
      </Cluster>
      <Cluster title="Choose files">
        <div className="toolbar"><SearchBox saveKey="restore" label="Search backed up files" placeholder="Search backed up files: name, folder, .pdf, >10mb" value={q} onChange={setQ} /><span className="sub">{total.toLocaleString()} files with a backup on this drive</span></div>
        {!rows.length && <div className="blank"><b>No backed up files found.</b></div>}
        <ul className="rows">
          {rows.map(f => (
            <li key={f.id}>
              <div className="line">
                <label className="check"><input type="checkbox" checked={pick.has(f.id)} onChange={() => flip(f.id)} aria-label={"Select " + f.path} /></label>
                <span className="path" title={f.path}><bdi>{f.path}</bdi></span><span className="sub">{fmt(f.size)}</span>
                <PreviewButton id={f.id} ids={rows.map(x => x.id)} name={f.path} />
                {keepsVersions && <button onClick={() => showVersions(f.id)} aria-expanded={openV === f.id}>Older versions</button>}
              </div>
              {openV === f.id && (
                <div className="peer-roots">
                  {vers[f.id] === "busy" && <p className="sub">Looking on the drive…</p>}
                  {Array.isArray(vers[f.id]) && !(vers[f.id] as Version[]).length && <p className="sub">No older version of this file is kept on this drive.</p>}
                  {Array.isArray(vers[f.id]) && (vers[f.id] as Version[]).map(v => (
                    <Row key={v.version} title={`Version from ${v.at}`} desc={`${fmt(v.size)}. It is put next to where you restore, named “… (version date)”, so nothing is overwritten.`}>
                      <button onClick={() => go([{ id: f.id, dest, version: v.version }])}>Restore this version</button>
                    </Row>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
        {rows.length < total && <div><button onClick={showMore} disabled={more}>{more ? "Loading..." : `Show more (${(total - rows.length).toLocaleString()} more)`}</button></div>}
      </Cluster>
      {err && <p className="err">{err}</p>}
      <div><button className="primary" disabled={!pick.size || !dest} onClick={() => go([...pick].map(id => ({ id, dest })))}>Restore {pick.size} selected</button></div>
    </Group>
  );
}
