import { useEffect, useState } from "react";
import { api, useStored } from "./api";
import { PathPicker } from "./PathList";

interface Info { target: string; personal: string[]; pc: string[] }
const kinds = ["Documents", "Images", "Videos", "Music", "Archives", "Code"];

export function Organize({ busy, onJob }: { busy: boolean; onJob: () => void }) {
  const [info, setInfo] = useState<Info | null>(null);
  const [scope, setScope] = useStored<"personal" | "pc">("organize.scope", "personal");
  const [target, setTarget] = useStored("organize.target", ""); const [err, setErr] = useState("");
  useEffect(() => { api<Info>("/api/organize/info").then(i => { setInfo(i); setTarget(t => t || i.target); }); }, []);
  const run = async () => {
    try { setErr(""); await api("/api/organize", "POST", { scope, target }); onJob(); } catch (e) { setErr((e as Error).message); }
  };
  return (
    <>
      <section className="block">
        <h2>Organize my PC into one folder</h2>
        <p className="sub">Finds your documents, pictures, videos, music and archives and copies them into one tidy folder, sorted by type and year. Your original files are not touched, and no external drive is needed. Running it again only adds new files.</p>
        <fieldset>
          <legend>What to search</legend>
          <label className="check"><input type="radio" name="scope" checked={scope === "personal"} onChange={() => setScope("personal")} /> My personal folders: {info?.personal.map(p => p.split(/[\\/]/).pop()).join(", ")}</label>
          <label className="check"><input type="radio" name="scope" checked={scope === "pc"} onChange={() => setScope("pc")} /> The whole PC: drives {info?.pc.join(", ")}. Skips Windows, Program Files and app data. Code files are left out.</label>
        </fieldset>
        <label>Put the organized folder here<PathPicker value={target} onChange={setTarget} /></label>
        <p className="sub">Sorted into: {kinds.join(", ")}. Each file is placed in a folder by type and then by year, for example Images/2025. A list of where every file came from is saved as organized-index.json in that folder. Make sure the drive has enough free space; the tool checks first.</p>
        {err && <p className="err">{err}</p>}
        <div><button className="primary" onClick={run} disabled={busy || !target.trim()}>Organize my PC</button></div>
      </section>
    </>
  );
}
