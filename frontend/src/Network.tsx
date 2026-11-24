import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { ask } from "./Dialog";
import { PathList } from "./PathList";
import { Select } from "./Select";

interface Agent {
  running: boolean; port: number | null; addresses: string[]; name: string; roots: { label: string; path: string }[]; auto_off_hours: number;
  pairing: { code: string; expires_in: number } | null; clients: { id: string; name: string; added: string; last_seen: string }[];
  connected: { id: string; name: string; seconds_ago: number; reading: string }[];
  log: { at: string; who: string; what: string; path: string; status: number }[]; fingerprint: string;
}
interface Peer { id: string; name: string; host: string; port: number; fingerprint: string; added: string; last_seen: string; roots: string[] }
interface Found { id: string; name: string; host: string; port: number; paired: boolean }
interface PeerRoots { roots: { label: string; chosen: boolean }[] }

const hours = [{ value: "0", label: "Never (stays on until I turn it off)" }, { value: "1", label: "After 1 hour" }, { value: "4", label: "After 4 hours" },
  { value: "8", label: "After 8 hours" }, { value: "24", label: "After 24 hours" }];

function Share() {
  const [a, setA] = useState<Agent | null>(null); const [err, setErr] = useState(""); const [left, setLeft] = useState(0);
  const load = useCallback(async () => { try { setA(await api<Agent>("/api/agent")); } catch (e) { setErr((e as Error).message); } }, []);
  useEffect(() => { load(); const t = setInterval(load, 3000); return () => clearInterval(t); }, [load]);
  useEffect(() => { setLeft(a?.pairing?.expires_in ?? 0); }, [a?.pairing?.code, a?.pairing?.expires_in]);
  useEffect(() => { if (left <= 0) return; const t = setTimeout(() => setLeft(l => l - 1), 1000); return () => clearTimeout(t); }, [left]);
  const act = async (path: string, body?: unknown) => { try { setErr(""); setA(await api<Agent>(path, "POST", body ?? {})); } catch (e) { setErr((e as Error).message); } };
  if (!a) return <p className="sub">{err || "Loading..."}</p>;
  const revoke = async (id: string, name: string) => { if (await ask(`Remove ${name}? It will lose access at once and would have to be paired again.`, "Remove")) act("/api/agent/revoke", { id }); };
  return (
    <>
      <section className="block">
        <h2>Share this PC {a.running ? <span className="tag backed_up">On</span> : <span className="tag">Off</span>}</h2>
        <p className="sub">Let another PC that you pair with back up the folders you choose here. It can only read them, never change or delete anything, and only on your own network. It is off until you turn it on.</p>
        {err && <p className="err">{err}</p>}
        <div className="row">
          {a.running
            ? <button onClick={() => act("/api/agent/stop")}>Turn sharing off</button>
            : <button className="primary" onClick={() => act("/api/agent/start")}>Turn sharing on</button>}
          {a.running && <span className="sub">This PC is <b>{a.name}</b> at <b>{a.addresses.join(" or ") || "an unknown address"}</b>, port <b>{a.port}</b>.</span>}
        </div>
        {a.connected.length > 0 && <p className="warn">Connected now: {a.connected.map(c => `${c.name} (reading ${c.reading})`).join(", ")}</p>}
        <label>Turn sharing off by itself
          <Select label="Turn sharing off by itself" value={String(a.auto_off_hours)} onChange={v => act("/api/agent/settings", { auto_off_hours: Number(v) })} options={hours} />
        </label>
        <details><summary className="sub">The other PC cannot connect?</summary>
          <p className="sub">Both PCs must be on the same Wi-Fi or network. The first time, Windows asks whether to allow Ala Eh! File Backup: allow it on <b>private networks</b> only. This app never opens your router or the internet.</p>
        </details>
      </section>
      <PathList title="Folders to share" hint="Only these folders can be read by a paired PC. Nothing else on this PC is visible, and this app's own data is never shared."
        items={a.roots.map(r => r.path)} onChange={v => act("/api/agent/roots", { roots: v })} />
      <section className="block">
        <h2>Pair another PC</h2>
        <p className="sub">Show a code here, then type it on the other PC under <b>PCs I back up</b>. The code works once and for 5 minutes. After 5 wrong tries it stops working.</p>
        {a.pairing && left > 0
          ? <div><p className="pair-code" aria-live="polite">{a.pairing.code}</p><p className="sub">Valid for {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")} more. This PC: {a.addresses[0] ?? ""} port {a.port}. Identity {a.fingerprint}.</p></div>
          : <div><button className="primary" disabled={!a.running || !a.roots.length} onClick={() => act("/api/agent/pairing")}>Show a pairing code</button>
            {(!a.running || !a.roots.length) && <span className="sub"> {a.running ? "Choose a folder to share first." : "Turn sharing on first."}</span>}</div>}
        <h2>PCs allowed to read this PC</h2>
        <ul className="rows">
          {a.clients.map(c => (
            <li key={c.id} className="line"><span className="grow"><b>{c.name}</b><br /><span className="sub">Paired {c.added || "earlier"}</span></span>
              <button onClick={() => revoke(c.id, c.name)}>Remove</button></li>
          ))}
          {!a.clients.length && <li className="sub">None yet</li>}
        </ul>
      </section>
      <section className="block">
        <h2>Recent activity</h2>
        <ul className="rows">
          {a.log.slice(0, 12).map((l, i) => <li key={i} className="line"><span className="sub">{l.at}</span><span className="grow"><b>{l.who}</b> {l.what} <bdi className="sub">{l.path}</bdi></span><span className="sub">{l.status}</span></li>)}
          {!a.log.length && <li className="sub">Nothing yet</li>}
        </ul>
      </section>
    </>
  );
}

function Peers() {
  const [peers, setPeers] = useState<Peer[]>([]); const [err, setErr] = useState(""); const [msg, setMsg] = useState("");
  const [found, setFound] = useState<Found[] | null>(null); const [finding, setFinding] = useState(false);
  const [host, setHost] = useState(""); const [port, setPort] = useState("5200"); const [code, setCode] = useState(""); const [pairing, setPairing] = useState(false);
  const [open, setOpen] = useState<string | null>(null); const [roots, setRoots] = useState<PeerRoots["roots"]>([]); const [rootErr, setRootErr] = useState("");
  const load = useCallback(async () => { try { setPeers(await api<Peer[]>("/api/peers")); } catch (e) { setErr((e as Error).message); } }, []);
  useEffect(() => { load(); }, [load]);
  const find = async () => { setFinding(true); setErr(""); try { setFound(await api<Found[]>("/api/peers/discover", "POST", {})); } catch (e) { setErr((e as Error).message); } setFinding(false); };
  const pair = async () => {
    setPairing(true); setErr(""); setMsg("");
    try { const p = await api<Peer>("/api/peers/pair", "POST", { host: host.trim(), port: Number(port) || 5200, code }); setMsg(`Paired with ${p.name}. Choose which of its folders to back up.`); setCode(""); setHost(""); setFound(null); await load(); chooseFolders(p.id); }
    catch (e) { setErr((e as Error).message); }
    setPairing(false);
  };
  const chooseFolders = async (id: string) => {
    if (open === id) return setOpen(null);
    setOpen(id); setRoots([]); setRootErr("");
    try { setRoots((await api<PeerRoots>(`/api/peers/${id}/roots`)).roots); } catch (e) { setRootErr((e as Error).message); }
  };
  const toggle = async (id: string, label: string, on: boolean) => {
    const next = roots.map(r => (r.label === label ? { ...r, chosen: on } : r));
    setRoots(next);
    try { await api(`/api/peers/${id}/sources`, "POST", { roots: next.filter(r => r.chosen).map(r => r.label) }); await load(); } catch (e) { setRootErr((e as Error).message); }
  };
  const forget = async (p: Peer) => { if (await ask(`Forget ${p.name}? Backups already made stay on your drive, but it will not be backed up any more.`, "Forget")) { await api(`/api/peers/${p.id}/forget`, "POST", {}); setOpen(null); load(); } };
  return (
    <>
      <section className="block">
        <h2>PCs I back up</h2>
        <p className="sub">Back up folders of another PC to this PC's backup drive, over your network. On that PC, turn on <b>Share this PC</b> and show a pairing code. This PC must be on and running this app while it backs up.</p>
        {msg && <p className="msg" role="status">{msg}</p>}
        {err && <p className="err">{err}</p>}
        <ul className="rows">
          {peers.map(p => (
            <li key={p.id}>
              <div className="line"><span className="grow"><b>{p.name}</b> <span className="sub">{p.host}:{p.port}</span><br />
                <span className="sub">{p.roots.length ? `Backing up: ${p.roots.join(", ")}.` : "No folders chosen yet."} {p.last_seen ? `Last reached ${p.last_seen}.` : ""}</span></span>
                <button onClick={() => chooseFolders(p.id)}>{open === p.id ? "Close" : "Choose folders"}</button>
                <button onClick={() => forget(p)}>Forget</button></div>
              {open === p.id && (
                <div className="block">
                  {rootErr && <p className="err">{rootErr}</p>}
                  {!rootErr && !roots.length && <p className="sub">Asking {p.name}...</p>}
                  {roots.map(r => <label key={r.label} className="check"><input type="checkbox" checked={r.chosen} onChange={e => toggle(p.id, r.label, e.target.checked)} /> {r.label}</label>)}
                  {roots.length > 0 && <p className="sub">Then open <b>New files</b> (or Files) to choose what to keep, and click <b>Back up now</b>.</p>}
                </div>
              )}
            </li>
          ))}
          {!peers.length && <li className="sub">No PC paired yet</li>}
        </ul>
      </section>
      <section className="block">
        <h2>Add a PC</h2>
        <div className="row"><button onClick={find} disabled={finding}>{finding ? "Looking..." : "Find PCs on this network"}</button></div>
        {found && (
          <ul className="rows">
            {found.map(f => <li key={f.id} className="line"><span className="grow"><b>{f.name}</b> <span className="sub">{f.host}:{f.port}{f.paired ? " (already paired)" : ""}</span></span>
              <button onClick={() => { setHost(f.host); setPort(String(f.port)); }}>Use</button></li>)}
            {!found.length && <li className="sub">No PC is sharing right now. Turn on Share this PC on the other PC, or type its address below.</li>}
          </ul>
        )}
        <div className="fields">
          <label>Its address<input value={host} onChange={e => setHost(e.target.value)} placeholder="192.168.1.40" inputMode="decimal" /></label>
          <label>Port<input value={port} onChange={e => setPort(e.target.value)} inputMode="numeric" /></label>
          <label>6-digit code<input value={code} onChange={e => setCode(e.target.value)} inputMode="numeric" maxLength={7} placeholder="123456" autoComplete="off" /></label>
        </div>
        <div><button className="primary" onClick={pair} disabled={pairing || !host.trim() || code.replace(/\D/g, "").length !== 6}>{pairing ? "Pairing..." : "Pair"}</button></div>
      </section>
    </>
  );
}

export function Network() {
  return <><Peers /><Share /></>;
}
