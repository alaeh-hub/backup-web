import { useCallback, useEffect, useState } from "react";
import { api, fmt, BigDir, FileRow } from "./api";
import { FileIcon, Icon } from "./ui";
import { PreviewButton } from "./Preview";

export function Biggest({ onChange }: { onChange: () => void }) {
  const [d, setD] = useState<{ folders: BigDir[]; files: FileRow[] } | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(async () => { try { setErr(""); setD(await api("/api/biggest")); } catch (e) { setErr((e as Error).message); } }, []);
  useEffect(() => { load(); }, [load]);
  const folder = async (f: BigDir) => {
    const on = f.selected < f.files;
    setD(x => x && { ...x, folders: x.folders.map(y => y.dir === f.dir ? { ...y, selected: on ? y.files : 0, review: 0 } : y) });
    try { await api("/api/files/select", "POST", { selected: on, dir: f.dir }); onChange(); } catch { await load(); }
  };
  const file = async (f: FileRow) => {
    const on = !f.selected;
    setD(x => x && { ...x, files: x.files.map(y => y.id === f.id ? { ...y, selected: on ? 1 : 0, review: false } : y) });
    try { await api("/api/files/select", "POST", { selected: on, ids: [f.id] }); onChange(); } catch { await load(); }
  };
  if (err) return <p className="err">Could not load the biggest items: {err}</p>;
  if (!d) return <p className="sub">Loading...</p>;
  return (
    <>
      <h2>Folders holding the most data</h2>
      <p className="sub">Size counts the files directly inside each folder. The switch affects those files.</p>
      <ul className="rows">
        {d.folders.map(f => (
          <li key={f.dir} className="line">
            <label className="switch"><input type="checkbox" checked={f.selected === f.files} onChange={() => folder(f)} aria-label={"Back up " + f.dir} /><span /></label>
            <Icon name="folder" /><span className="path" title={f.dir}><bdi>{f.dir}</bdi></span><span className="sub">{f.files.toLocaleString()} files{f.review ? `, ${f.review.toLocaleString()} to review` : ""}</span><strong>{fmt(f.bytes)}</strong>
          </li>
        ))}
      </ul>
      <h2>Largest files</h2>
      <ul className="rows">
        {d.files.map(f => (
          <li key={f.id} className="line">
            <label className="switch"><input type="checkbox" checked={!!f.selected} onChange={() => file(f)} aria-label={"Back up " + f.path} /><span /></label>
            <FileIcon name={f.path} /><span className="path" title={f.path}><bdi>{f.path}</bdi></span><strong>{fmt(f.size)}</strong>
            <PreviewButton id={f.id} ids={d.files.map(x => x.id)} name={f.path} />
          </li>
        ))}
      </ul>
    </>
  );
}
