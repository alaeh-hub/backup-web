import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { FileIcon, Icon } from "./ui";
import { PreviewButton } from "./Preview";
import { SearchBox } from "./SearchBox";
import { smartFilter } from "./smart";
import { ask } from "./Dialog";
import { api, fmt, label, useStored, Explore, FolderRow, Suggestion } from "./api";

interface Item { kind: "folder" | "file"; path: string; name: string; id?: string; files: number; bytes: number; parent?: string }
interface Data { items: Item[]; count: number; files: number; bytes: number }

const crumbsOf = (cwd: string) => {
  const sep = cwd.includes("\\") ? "\\" : "/";
  const parts = cwd.split(/[\\/]/).filter(Boolean);
  return parts.map((n, i) => ({ n, p: (cwd.startsWith("/") ? "/" : "") + parts.slice(0, i + 1).join(sep) + (i === 0 && /^[A-Za-z]:$/.test(n) ? sep : "") }));
};

/** Browse inside one new folder and choose by folder or file. */
function Inside({ cwd, setCwd, onChange }: { cwd: string; setCwd: (p: string) => void; onChange: () => void }) {
  const [ex, setEx] = useState<Explore | null>(null);
  const seq = useRef(0);
  const load = useCallback(async () => { const my = ++seq.current; const r = await api<Explore>(`/api/explore?path=${encodeURIComponent(cwd)}`); if (my === seq.current) setEx(r); }, [cwd]);
  useEffect(() => { load(); }, [load]);
  // Update the screen first, then tell the server. Nothing waits on a reload.
  const patch = (fn: (e: Explore) => Explore) => setEx(e => (e ? fn(e) : e));
  const sel = async (body: object, local: (e: Explore) => Explore) => {
    patch(local);
    try { await api("/api/files/select", "POST", body); onChange(); } catch { await load(); }
  };
  const mark = (e: Explore, on: boolean): Explore => ({ ...e, folders: e.folders.map(x => ({ ...x, selected: on ? x.files : 0, review: 0 })), files: e.files.map(x => ({ ...x, selected: on ? 1 : 0, review: false })) });
  const folder = (f: FolderRow) => { const on = f.selected < f.files; return sel({ selected: on, prefix: f.path }, e => ({ ...e, folders: e.folders.map(x => x.path === f.path ? { ...x, selected: on ? x.files : 0, review: 0 } : x) })); };
  return (
    <>
      <div className="toolbar">
        <button onClick={() => setCwd("")}>Back to the list</button>
        {crumbsOf(cwd).map(c => <button key={c.p} onClick={() => setCwd(c.p)} disabled={c.p === cwd}>{c.n}</button>)}
        {ex?.parent && <button onClick={() => setCwd(ex.parent!)}>Up</button>}
        <span className="grow" />
        <button className="primary" onClick={() => sel({ selected: true, prefix: cwd }, e => mark(e, true))}>Back up this whole folder</button>
        <button title="Files added to this folder later stay skipped too" onClick={() => sel({ selected: false, prefix: cwd }, e => mark(e, false))}>Skip this whole folder</button>
      </div>
      <ul className="rows">
        {ex?.folders.map(f => (
          <li key={f.path} className="line">
            <label className="switch"><input type="checkbox" checked={f.selected === f.files} onChange={() => folder(f)} aria-label={"Back up " + f.name} /><span /></label>
            <button className="linkish grow" title={f.path} onClick={() => setCwd(f.path)}><Icon name="folder" /><span className="path"><bdi>{f.name}</bdi></span></button>
            <span className="sub">{f.files.toLocaleString()} files</span><strong>{fmt(f.bytes)}</strong>
          </li>
        ))}
        {ex?.files.map(f => (
          <li key={f.id} className="line">
            <label className="switch"><input type="checkbox" checked={!!f.selected} onChange={() => sel({ selected: !f.selected, ids: [f.id] }, e => ({ ...e, files: e.files.map(x => x.id === f.id ? { ...x, selected: f.selected ? 0 : 1, review: false } : x) }))} aria-label={"Back up " + f.path} /><span /></label>
            <span className="path" title={f.path}><bdi>{f.path.split(/[\\/]/).pop()}</bdi></span>
            <span className="sub">{f.review ? "To review" : f.selected ? label[f.status] : "Skipped"}</span><strong>{fmt(f.size)}</strong>
            <PreviewButton id={f.id} ids={ex.files.map(x => x.id)} name={f.path.split(/[\/]/).pop() ?? f.path} />
          </li>
        ))}
      </ul>
    </>
  );
}

export function Review({ onChange, mode = "review" }: { onChange: () => void; mode?: "review" | "selected" }) {
  const chosen = mode === "selected", url = chosen ? "/api/selected" : "/api/review";
  const [cwd, setCwd] = useStored(mode + ".cwd", ""); const [d, setD] = useState<Data | null>(null);
  const [err, setErr] = useState(""); const [q, setQ] = useState("");
  const [sug, setSug] = useState<{ total: number; items: Suggestion[] } | null>(null);
  const load = useCallback(async () => {
    try { setErr(""); setD(await api<Data>(url)); } catch (e) { setErr((e as Error).message); }
    if (!chosen) api<{ total: number; items: Suggestion[] }>("/api/suggested").then(setSug).catch(() => setSug(null));
  }, [url, chosen]);
  useEffect(() => { if (!cwd) load(); }, [cwd, load]);
  if (cwd) return <Inside cwd={cwd} setCwd={setCwd} onChange={onChange} />;
  if (err) return <p className="err">Could not load the list: {err}. If you just updated the app, restart py app.py.</p>;
  if (!d) return <p className="sub">Loading...</p>;
  // The item disappears at once; the server catches up in the background.
  const decide = async (it: Item, selected: boolean) => {
    const left = d.items.length - 1;
    setD(x => x && { ...x, items: x.items.filter(i => !(i.kind === it.kind && i.path === it.path)), count: x.count - 1, files: x.files - it.files, bytes: x.bytes - it.bytes });
    try { await api("/api/files/select", "POST", it.kind === "folder" ? { selected, prefix: it.path } : { selected, ids: [it.id] }); onChange(); if (!left && d.count > 1) await load(); }
    catch { await load(); }
  };
  // Suggested files: the new files most likely to matter. Deciding them also removes them from the list below.
  const decideSug = async (ids: string[], selected: boolean) => {
    setSug(x => x && { ...x, items: x.items.filter(i => !ids.includes(i.id)) });
    try { await api("/api/files/select", "POST", { selected, ids }); onChange(); await load(); } catch { await load(); }
  };
  const all = async (selected: boolean) => {
    if (chosen && !(await ask("Remove every file from the backup list?", "Remove all"))) return;
    setD(x => x && { ...x, items: [], count: 0, files: 0, bytes: 0 });
    try { await api("/api/files/select", "POST", { selected, filter: chosen ? { status: "all", sel: 1 } : { status: "review" } }); onChange(); } catch { await load(); }
  };
  const shown = smartFilter(d.items, q, it => it.path, it => ({ size: it.bytes, ext: it.kind === "file" ? (/\.[^.\/]+$/.exec(it.name)?.[0] ?? "") : "" }));
  const searching = q.trim() !== "";
  return (
    <>
      <div className="toolbar">
        <SearchBox saveKey={mode} label={chosen ? "Search chosen files" : "Search new files"} placeholder={chosen ? "Search chosen files and folders" : "Search new files and folders: name, .pdf, >10mb"} value={q} onChange={setQ} />
      </div>
      <div className="toolbar">
        <span className="sub grow">{chosen
          ? `${d.files.toLocaleString()} files chosen for backup, ${fmt(d.bytes)}. A folder where everything is chosen is one item; open it to look inside.`
          : `${d.files.toLocaleString()} new files, ${fmt(d.bytes)}. A new folder is shown as one item; open it to look inside.`}</span>
        {!chosen && <button className="primary" onClick={() => all(true)} disabled={!d.count || searching} title={searching ? "Clear the search to act on everything" : undefined}>Back up all</button>}
        <button onClick={() => all(false)} disabled={!d.count || searching} title={searching ? "Clear the search to act on everything" : undefined}>{chosen ? "Remove all" : "Skip all"}</button>
      </div>
      {!chosen && !searching && !!sug?.items.length && (
        <section className="suggest" aria-label="Suggested new files">
          <div className="suggest-head">
            <div><h2>Start with these</h2><p className="sub">The {sug.items.length} new files you most likely use: recently opened or edited, of the kinds people keep, in the places people keep them.</p></div>
            <button className="primary" onClick={() => decideSug(sug.items.map(i => i.id), true)}>Back up these {sug.items.length}</button>
          </div>
          <ul className="rows">
            {sug.items.map(i => (
              <li key={i.id} className="line">
                <FileIcon name={i.name} />
                <span className="sg-text" title={i.path}>
                  <span className="sg-head"><b className="sg-name">{i.name}</b><span className="sub sg-where"><bdi>in {i.parent}</bdi></span></span>
                  <span className="sub">{i.reason}</span>
                </span>
                <strong>{fmt(i.bytes)}</strong>
                <PreviewButton id={i.id} ids={sug.items.map(x => x.id)} name={i.name} />
                <button className="primary" onClick={() => decideSug([i.id], true)}>Back up</button>
                <button onClick={() => decideSug([i.id], false)}>Skip</button>
              </li>
            ))}
          </ul>
          <h2 className="suggest-rest">Everything else that is new</h2>
        </section>
      )}
      <ul className="rows">
        <AnimatePresence initial={false} mode="popLayout">
        {shown.map(it => (
          <motion.li key={it.kind + it.path} className="line" layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, x: 48 }} transition={{ type: "spring", stiffness: 500, damping: 40 }}>
            {it.kind === "folder"
              ? <button className="linkish grow" title={it.path} onClick={() => setCwd(it.path)}><Icon name="folder" /><span className="path"><bdi>{it.name}</bdi></span></button>
              : <><FileIcon name={it.name} /><span className="path" title={it.path}><bdi>{it.name} <span className="sub">in {it.parent}</span></bdi></span></>}
            <span className="sub">{it.kind === "folder" ? `${it.files.toLocaleString()} files` : "file"}</span><strong>{fmt(it.bytes)}</strong>
            {it.kind === "file" && it.id && <PreviewButton id={it.id} ids={shown.filter(x => x.kind === "file" && x.id).map(x => x.id!)} name={it.name} />}
            {!chosen && <button className="primary" onClick={() => decide(it, true)}>Back up</button>}
            <button onClick={() => decide(it, false)}>{chosen ? "Remove" : "Skip"}</button>
          </motion.li>
        ))}
        </AnimatePresence>
        {searching && !!d.count && !shown.length && <li className="sub">Nothing matches “{q}”. Try fewer words.</li>}
        {!d.count && <li className="sub">{chosen ? "Nothing is chosen for backup yet. Pick files in New files or use a Quick pick in Files." : "Nothing new to review. New files will appear here after you scan."}</li>}
        {d.count > d.items.length && <li className="sub">Showing the {d.items.length} biggest of {d.count.toLocaleString()} items. Decide these and the rest will appear.</li>}
      </ul>
    </>
  );
}
