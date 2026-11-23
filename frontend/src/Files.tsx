import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { Icon } from "./ui";
import { Presets } from "./Presets";
import { Types } from "./Types";
import { Biggest } from "./Biggest";
import { api, fmt, label, useStored, Explore, FileRow, FolderRow, Status } from "./api";

interface Page { total: number; total_bytes: number; rows: FileRow[]; exts: [string, number][] }
const LIMIT = 200;

function FileBrowser({ onChange }: { onChange: () => void }) {
  const [q, setQ] = useState(""); const [status, setStatus] = useState("all"); const [ext, setExt] = useState("");
  const [sort, setSort] = useState("name"); const [dir, setDir] = useState("asc");
  const [rows, setRows] = useState<FileRow[]>([]); const [total, setTotal] = useState(0); const [bytes, setBytes] = useState(0);
  const [exts, setExts] = useState<[string, number][]>([]);
  const [cwd, setCwd] = useStored("files.cwd", ""); const [ex, setEx] = useState<Explore | null>(null);
  const explorer = !q && !ext && status === "all";
  const params = `q=${encodeURIComponent(q)}&status=${status}&ext=${encodeURIComponent(ext)}&sort=${sort}&dir=${dir}`;

  const seqL = useRef(0); const seqE = useRef(0);   // a slow, older answer must never replace a newer one
  const load = useCallback(async (offset = 0) => {
    const my = ++seqL.current;
    const p = await api<Page>(`/api/files?${params}&offset=${offset}&limit=${LIMIT}`);
    if (my !== seqL.current) return;
    setRows(r => offset ? [...r, ...p.rows] : p.rows); setTotal(p.total); setBytes(p.total_bytes);
    if (!offset) setExts(p.exts);
  }, [params]);
  const loadEx = useCallback(async () => { const my = ++seqE.current; const r = await api<Explore>(`/api/explore?path=${encodeURIComponent(cwd)}`); if (my === seqE.current) setEx(r); }, [cwd]);
  useEffect(() => { if (explorer) loadEx(); }, [explorer, loadEx]);
  useEffect(() => { if (explorer) return; const t = setTimeout(() => load(0), 250); return () => clearTimeout(t); }, [load, explorer]);
  const refresh = async () => { if (explorer) await loadEx(); else await load(0); onChange(); };

  const toggle = async (f: FileRow) => {
    const selected = f.selected ? 0 : 1;
    setRows(rs => rs.map(x => x.id === f.id ? { ...x, selected } : x));
    setEx(e => e && { ...e, files: e.files.map(x => x.id === f.id ? { ...x, selected, review: false } : x) });
    try { await api("/api/files/select", "POST", { selected: !!selected, ids: [f.id] }); onChange(); } catch { await refresh(); }
  };
  const bulk = async (selected: boolean) => {
    if (explorer && !cwd && !confirm(selected ? "Choose every scanned file for backup?" : "Skip every scanned file?")) return;
    try { await api("/api/files/select", "POST", explorer && cwd ? { selected, prefix: cwd } : { selected, filter: { q, status, ext } }); } catch { /* the refresh below shows the real state */ }
    await refresh();
  };
  const folder = async (f: FolderRow) => {
    const on = f.selected < f.files;
    setEx(e => e && { ...e, folders: e.folders.map(x => x.path === f.path ? { ...x, selected: on ? x.files : 0, review: 0 } : x) });
    try { await api("/api/files/select", "POST", { selected: on, prefix: f.path }); onChange(); } catch { await refresh(); }
  };
  const crumbs = () => {
    if (!cwd) return [];
    const parts = cwd.split(/[\\/]/).filter(Boolean); const sep = cwd.includes("\\") ? "\\" : "/";
    return parts.map((n, i) => ({ n, p: (cwd.startsWith("/") ? "/" : "") + parts.slice(0, i + 1).join(sep) + (i === 0 && /^[A-Za-z]:$/.test(n) ? sep : "") }));
  };

  const decide = async (selected: boolean) => { await api("/api/files/select", "POST", { selected, filter: { q, status: "review", ext } }); await load(0); onChange(); };
  return (
    <>
      {status === "review" && (
        <div className="toolbar">
          <span className="sub grow">New files found since your last review. Skipped files are not shown here.</span>
          <button className="primary" onClick={() => decide(true)}>Back up all shown</button>
          <button onClick={() => decide(false)}>Skip all shown</button>
        </div>
      )}
      <div className="toolbar">
        <input aria-label="Search files" placeholder="Search by name or folder" value={q} onChange={e => setQ(e.target.value)} />
        <select aria-label="Status" value={status} onChange={e => setStatus(e.target.value)}>
          <option value="all">All statuses</option><option value="review">To review (new files)</option><option value="skipped">Skipped (not backed up)</option>{(Object.keys(label) as Status[]).map(s => <option key={s} value={s}>{label[s]}</option>)}
        </select>
        <select aria-label="File type" value={ext} onChange={e => setExt(e.target.value)}>
          <option value="">All types</option>{exts.map(([e, n]) => <option key={e} value={e}>{e} ({n})</option>)}
        </select>
        <select aria-label="Sort by" value={sort} onChange={e => setSort(e.target.value)}>
          <option value="name">Sort by name</option><option value="size">Sort by size</option><option value="mtime">Sort by modified</option><option value="status">Sort by status</option>
        </select>
        <button onClick={() => setDir(dir === "asc" ? "desc" : "asc")}>{dir === "asc" ? "Ascending" : "Descending"}</button>
      </div>
      <div className="toolbar">
        <span className="sub grow">{explorer ? "Open a folder to see what is inside. Search or filter to see a flat list of files." : `${total.toLocaleString()} files, ${fmt(bytes)}`}</span>
        <button onClick={() => bulk(true)}>{explorer && cwd ? "Back up this whole folder" : explorer ? "Select everything" : "Select all shown"}</button>
        <button onClick={() => bulk(false)}>{explorer && cwd ? "Skip this whole folder" : explorer ? "Skip everything" : "Select none shown"}</button>
      </div>
      {explorer ? (
        <>
          <div className="toolbar">
            <button onClick={() => setCwd("")} disabled={!cwd}>All folders</button>
            {crumbs().map(c => <button key={c.p} onClick={() => setCwd(c.p)} disabled={c.p === cwd}>{c.n}</button>)}
            {ex?.parent !== null && ex?.parent !== undefined && cwd && <button onClick={() => setCwd(ex.parent ?? "")}>Up</button>}
          </div>
          <ul className="rows">
            {ex?.folders.map(f => (
              <li key={f.path} className="line">
                <label className="switch"><input type="checkbox" checked={f.selected === f.files} onChange={() => folder(f)} aria-label={"Back up " + f.name} /><span /></label>
                <button className="linkish grow" title={f.path} onClick={() => setCwd(f.path)}><Icon name="folder" /><span className="path"><bdi>{f.name}</bdi></span></button>
                <span className="sub">{f.files.toLocaleString()} files{f.review ? `, ${f.review.toLocaleString()} to review` : ""}</span>
                <strong>{fmt(f.bytes)}</strong>
              </li>
            ))}
            {ex && !ex.folders.length && !ex.files.length && <li className="sub">Nothing here. Click “Scan files” first.</li>}
          </ul>
          {!!ex?.files.length && (
            <div className="scroll"><table>
              <thead><tr><th>Back up</th><th>File</th><th>Size</th><th>Modified</th><th>Status</th></tr></thead>
              <tbody>{ex.files.map(f => (
                <tr key={f.id}>
                  <td><label className="switch"><input type="checkbox" checked={!!f.selected} onChange={() => toggle(f)} aria-label={"Back up " + f.path} /><span /></label></td>
                  <td className="path" title={f.path}><bdi>{f.path.split(/[\\/]/).pop()}</bdi></td><td className="nowrap">{fmt(f.size)}</td>
                  <td className="nowrap">{new Date(f.mtime * 1000).toLocaleDateString()}</td><td><span className={"tag " + f.status}>{f.review ? "To review" : f.selected ? label[f.status] : "Skipped"}</span></td>
                </tr>))}</tbody>
            </table></div>
          )}
        </>
      ) : (<>
      <div className="scroll">
        <table>
          <thead><tr><th>Back up</th><th>File</th><th>Size</th><th>Modified</th><th>Status</th></tr></thead>
          <tbody>
            {rows.map(f => (
              <tr key={f.id}>
                <td><label className="switch"><input type="checkbox" checked={!!f.selected} onChange={() => toggle(f)} aria-label={"Back up " + f.path} /><span /></label></td>
                <td className="path" title={f.path}><bdi>{f.path}</bdi></td><td className="nowrap">{fmt(f.size)}</td>
                <td className="nowrap">{new Date(f.mtime * 1000).toLocaleDateString()}</td><td><span className={"tag " + f.status}>{f.review ? "To review" : f.selected ? label[f.status] : "Skipped"}</span></td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={5} className="empty">No files match. Click “Scan files” first.</td></tr>}
          </tbody>
        </table>
      </div>
      {rows.length < total && <button onClick={() => load(rows.length)}>Show more ({total - rows.length} left)</button>}
      </>)}
    </>
  );
}

type View = "folders" | "types" | "biggest";
export function Files({ onChange }: { onChange: () => void }) {
  const [view, setView] = useStored<View>("files.view", "folders"); const [ver, setVer] = useState(0);
  const changed = () => { setVer(v => v + 1); onChange(); };
  const names: [View, string][] = [["folders", "Folders"], ["types", "By type"], ["biggest", "Biggest first"]];
  return (
    <>
      <Presets onApplied={changed} />
      <nav className="seg" aria-label="Ways to choose files">
        {names.map(([k, n]) => (
          <button key={k} aria-pressed={view === k} onClick={() => setView(k)}>
            {view === k && <motion.span layoutId="seg-pill" className="seg-pill" transition={{ type: "spring", stiffness: 520, damping: 40 }} />}
            {n}
          </button>
        ))}
      </nav>
      {view === "folders" && <FileBrowser key={ver} onChange={onChange} />}
      {view === "types" && <Types key={ver} onChange={onChange} />}
      {view === "biggest" && <Biggest key={ver} onChange={onChange} />}
    </>
  );
}
