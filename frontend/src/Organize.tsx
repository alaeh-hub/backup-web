import { useEffect, useState } from "react";
import { api, useStored } from "./api";
import { Cluster, Group, Row } from "./Panel";
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
    <Group title="Organize my PC into one folder" lead="Copies your documents, pictures, videos, music and archives into one tidy folder, sorted by type and year. Your original files are not touched, and no external drive is needed. Running it again only adds new files.">
      <Cluster title="What to search">
        <Row wide title="Search" desc="Code files are left out either way.">
          <label className="check"><input type="radio" name="scope" checked={scope === "personal"} onChange={() => setScope("personal")} /> My personal folders: {info?.personal.map(p => p.split(/[\/]/).pop()).join(", ")}</label>
          <label className="check"><input type="radio" name="scope" checked={scope === "pc"} onChange={() => setScope("pc")} /> The whole PC: drives {info?.pc.join(", ")}. Skips Windows, Program Files and app data.</label>
        </Row>
      </Cluster>
      <Cluster title="Where it goes">
        <Row wide title="Organized folder" desc={`Sorted into: ${kinds.join(", ")}, then by year (for example Images/2025). A list of where every file came from is saved as organized-index.json there. The tool checks the drive has enough free space first.`}>
          <PathPicker value={target} onChange={setTarget} />
        </Row>
      </Cluster>
      {err && <p className="err">{err}</p>}
      <div><button className="primary" onClick={run} disabled={busy || !target.trim()}>Organize my PC</button></div>
    </Group>
  );
}
