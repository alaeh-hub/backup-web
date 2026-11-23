import { useEffect, useState } from "react";
import { api, Preset } from "./api";

interface Result { message: string; backed: number; skipped: number; bytes: number }

export function Presets({ onApplied }: { onApplied: () => void }) {
  const [list, setList] = useState<Preset[]>([]); const [msg, setMsg] = useState("");
  const [onlyNew, setOnlyNew] = useState(false); const [pending, setPending] = useState<{ key: string; text: string } | null>(null);
  useEffect(() => { api<Preset[]>("/api/presets").then(setList).catch(e => setMsg("Error: " + (e as Error).message)); }, []);
  const body = (key: string, dry: boolean) => ({ preset: key, replace_all: !onlyNew, dry });
  // First show what the pick would do, then apply it only after a second click.
  const preview = async (key: string) => {
    setMsg("");
    try { const r = await api<Result>("/api/presets/apply", "POST", body(key, true)); setPending({ key, text: r.message }); }
    catch (e) { setMsg("Error: " + (e as Error).message); }
  };
  const apply = async () => {
    if (!pending) return;
    try { const r = await api<Result>("/api/presets/apply", "POST", body(pending.key, false)); setMsg("Done. " + r.message); setPending(null); onApplied(); }
    catch (e) { setMsg("Error: " + (e as Error).message); }
  };
  return (
    <section className="block">
      <h2>Quick pick</h2>
      <p className="sub">Choose a starting point for the whole PC. You see what it will do before anything changes, and you can adjust afterwards.</p>
      <div className="presets">
        {list.map(p => <button key={p.key} className="preset" onClick={() => preview(p.key)}><b>{p.label}</b><span>{p.desc}</span></button>)}
      </div>
      <label className="check"><input type="checkbox" checked={onlyNew} onChange={e => { setOnlyNew(e.target.checked); setPending(null); }} /> Only decide files still waiting for review, keep my other choices</label>
      {pending && (
        <div className="row" role="status">
          <span className="grow">{pending.text}</span>
          <button className="primary" onClick={apply}>Apply</button>
          <button onClick={() => setPending(null)}>Cancel</button>
        </div>
      )}
      {msg && <p className="msg" role="status">{msg}</p>}
    </section>
  );
}
