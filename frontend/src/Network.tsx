import { useCallback, useEffect, useState } from "react";
import { api, useStored } from "./api";
import { ask } from "./Dialog";
import { Cluster, Group, Panel, Row, Switch } from "./Panel";
import { PathList } from "./PathList";
import { Select } from "./Select";

interface Agent {
  running: boolean; port: number | null; addresses: string[]; name: string; roots: { label: string; path: string }[]; auto_off_hours: number;
  pairing: { code: string; expires_in: number } | null; clients: { id: string; name: string; added: string; last_seen: string }[];
  connected: { id: string; name: string; seconds_ago: number; reading: string }[];
  log: { at: string; who: string; what: string; path: string; status: number }[]; fingerprint: string;
}
interface Peer {
  id: string; name: string; host: string; port: number; fingerprint: string; added: string; last_seen: string; roots: string[];
  state: "online" | "off" | "offline" | "removed" | "changed" | "error" | "unknown"; state_text: string; checked_at: number | null;
  scans: Record<string, { at: number; files: number; bytes: number }>;
}
interface Found { id: string; name: string; host: string; port: number; paired: boolean }
interface PeerRoots { roots: { label: string; chosen: boolean }[] }
type Section = "peers" | "share" | "activity";

/** How a paired PC is doing right now, as the app last asked it. */
const stateTag: Record<Peer["state"], { cls: string; label: string }> = {
  online: { cls: "backed_up", label: "Online" }, off: { cls: "lv-warn", label: "Sharing is off" }, offline: { cls: "lv-warn", label: "Not reachable" },
  removed: { cls: "lv-error", label: "Pairing removed" }, changed: { cls: "lv-error", label: "Identity changed" }, error: { cls: "lv-warn", label: "Not checked" }, unknown: { cls: "", label: "Checking…" },
};
const when = (t: number) => new Date(t * 1000).toLocaleString();

const hours = [{ value: "0", label: "Never (until I turn it off)" }, { value: "1", label: "After 1 hour" }, { value: "4", label: "After 4 hours" },
  { value: "8", label: "After 8 hours" }, { value: "24", label: "After 24 hours" }];

/** The PCs this PC backs up: who is paired, which of their folders are chosen, and how to add another. */
function Peers({ peers, reload, checking }: { peers: Peer[] | null; reload: (check?: boolean) => Promise<void>; checking: boolean }) {
  const [err, setErr] = useState(""); const [msg, setMsg] = useState("");
  const [found, setFound] = useState<Found[] | null>(null); const [finding, setFinding] = useState(false);
  const [host, setHost] = useState(""); const [port, setPort] = useState("5200"); const [code, setCode] = useState(""); const [pairing, setPairing] = useState(false);
  const [open, setOpen] = useState<string | null>(null); const [roots, setRoots] = useState<PeerRoots["roots"]>([]); const [rootErr, setRootErr] = useState("");
  const find = async () => { setFinding(true); setErr(""); try { setFound(await api<Found[]>("/api/peers/discover", "POST", {})); } catch (e) { setErr((e as Error).message); } setFinding(false); };
  const pair = async () => {
    setPairing(true); setErr(""); setMsg("");
    try { const p = await api<Peer>("/api/peers/pair", "POST", { host: host.trim(), port: Number(port) || 5200, code }); setMsg(`Paired with ${p.name}. Choose which of its folders to back up.`); setCode(""); setHost(""); setFound(null); await reload(); chooseFolders(p.id); }
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
    try { await api(`/api/peers/${id}/sources`, "POST", { roots: next.filter(r => r.chosen).map(r => r.label) }); await reload(); } catch (e) { setRootErr((e as Error).message); }
  };
  const forget = async (p: Peer) => { if (await ask(`Forget ${p.name}? Backups already made stay on your drive, but it will not be backed up any more.`, "Forget")) { await api(`/api/peers/${p.id}/forget`, "POST", {}); setOpen(null); reload(); } };
  return (
    <Group title="PCs I back up" lead="Copy folders of another PC to this PC's backup drive over your network. This PC must be on and running the app while it backs up.">
      {msg && <p className="msg" role="status">{msg}</p>}
      <Cluster title="Paired PCs">
        <div className="row"><button onClick={() => reload(true)} disabled={checking}>{checking ? "Checking…" : "Check now"}</button><span className="sub">Asks each PC whether it is on and sharing. Done by itself every few seconds while you look at this page.</span></div>
        {peers === null && <p className="sub">Loading…</p>}
        {peers && !peers.length && (
          <div className="blank"><b>No PC is paired yet.</b><span className="sub">On the other PC open Other PCs, turn on Share this PC and show a pairing code. Then add it below.</span></div>
        )}
        {peers && peers.length > 0 && (
          <ul className="rows">
            {peers.map(p => (
              <li key={p.id}>
                <div className="line">
                  <span className="grow"><b>{p.name}</b> <span className="sub">{p.host}:{p.port}</span> <span className={"tag " + stateTag[p.state].cls}>{stateTag[p.state].label}</span><br />
                    <span className="sub">{p.state === "online" || p.state === "unknown" ? "" : p.state_text + " "}{p.roots.length ? `Backing up ${p.roots.join(", ")}.` : "No folders chosen yet."} {p.last_seen ? `Last reached ${p.last_seen}.` : ""}</span>
                    {p.roots.filter(r => p.scans[r]).map(r => <span key={r} className="sub"><br />{r}: {p.scans[r].files.toLocaleString()} files, last scanned {when(p.scans[r].at)}{p.state !== "online" && p.state !== "unknown" ? " (old: that PC cannot be reached now)" : ""}</span>)}</span>
                  <button onClick={() => chooseFolders(p.id)} aria-expanded={open === p.id} disabled={p.state !== "online" && p.state !== "unknown"} title={p.state === "online" || p.state === "unknown" ? undefined : p.state_text}>{open === p.id ? "Close" : "Choose folders"}</button>
                  <button onClick={() => forget(p)}>Forget</button>
                </div>
                {open === p.id && (
                  <div className="peer-roots">
                    {rootErr && <p className="err">{rootErr}</p>}
                    {!rootErr && !roots.length && <p className="sub">Asking {p.name}…</p>}
                    {roots.map(r => <Row key={r.label} title={r.label} desc={r.chosen ? "Backed up" : "Not backed up"}><Switch checked={r.chosen} onChange={on => toggle(p.id, r.label, on)} label={`Back up ${r.label} from ${p.name}`} /></Row>)}
                    {roots.length > 0 && <p className="sub">Then open New files to choose what to keep, and click Back up now.</p>}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Cluster>
      <Cluster title="Add a PC">
        {err && <p className="err">{err}</p>}
        <Row title="Find it on this network" desc="Lists PCs that have Share this PC turned on right now.">
          <button onClick={find} disabled={finding}>{finding ? "Looking…" : "Find PCs"}</button>
        </Row>
        {found && (
          <ul className="rows">
            {found.map(f => <li key={f.id} className="line"><span className="grow"><b>{f.name}</b> <span className="sub">{f.host}:{f.port}{f.paired ? " (already paired)" : ""}</span></span>
              <button onClick={() => { setHost(f.host); setPort(String(f.port)); }}>Use</button></li>)}
            {!found.length && <li className="sub">No PC is sharing right now. Turn on Share this PC on the other PC, or type its address below.</li>}
          </ul>
        )}
        <Row wide title="Its address and the code it shows" desc="The code has 6 digits, works once, and runs out after 5 minutes.">
          <div className="fields three">
            <label>Address<input value={host} onChange={e => setHost(e.target.value)} placeholder="192.168.1.40" inputMode="decimal" autoComplete="off" /></label>
            <label>Port<input value={port} onChange={e => setPort(e.target.value)} inputMode="numeric" /></label>
            <label>Code<input value={code} onChange={e => setCode(e.target.value)} inputMode="numeric" maxLength={7} placeholder="123456" autoComplete="off" /></label>
          </div>
          <div><button className="primary" onClick={pair} disabled={pairing || !host.trim() || code.replace(/\D/g, "").length !== 6}>{pairing ? "Pairing…" : "Pair"}</button></div>
        </Row>
      </Cluster>
    </Group>
  );
}

/** This PC as the one being backed up: switch sharing on, choose folders, show a pairing code, see who may read it. */
function Share({ a, act, err }: { a: Agent | null; act: (path: string, body?: unknown) => Promise<void>; err: string }) {
  const [left, setLeft] = useState(0);
  useEffect(() => { setLeft(a?.pairing?.expires_in ?? 0); }, [a?.pairing?.code, a?.pairing?.expires_in]);
  useEffect(() => { if (left <= 0) return; const t = setTimeout(() => setLeft(l => l - 1), 1000); return () => clearTimeout(t); }, [left]);
  if (!a) return <Group title="Share this PC"><p className={err ? "err" : "sub"}>{err || "Loading…"}</p></Group>;
  const revoke = async (id: string, name: string) => { if (await ask(`Remove ${name}? It will lose access at once and would have to be paired again.`, "Remove")) act("/api/agent/revoke", { id }); };
  const ready = a.running && a.roots.length > 0;
  return (
    <Group title="Share this PC" lead="Let a PC you pair with back up the folders you choose. It can only read them, never change or delete anything, and only on your own network."
      aside={a.running ? <span className="tag backed_up">On</span> : <span className="tag">Off</span>}>
      {err && <p className="err">{err}</p>}
      <Cluster title="Status">
        <Row title={a.running ? "Sharing is on" : "Sharing is off"}
          desc={a.running ? <>This PC is <b>{a.name}</b> at <b>{a.addresses.join(" or ") || "an unknown address"}</b>, port <b>{a.port}</b>.</> : "It stays off until you turn it on, and is never reachable from the internet."}>
          {a.running ? <button onClick={() => act("/api/agent/stop")}>Turn sharing off</button> : <button className="primary" onClick={() => act("/api/agent/start")}>Turn sharing on</button>}
        </Row>
        {a.connected.length > 0 && <p className="warn">Connected now: {a.connected.map(c => `${c.name} (reading ${c.reading})`).join(", ")}</p>}
        <Row title="Turn sharing off by itself" desc="A safety net in case you forget.">
          <Select label="Turn sharing off by itself" value={String(a.auto_off_hours)} onChange={v => act("/api/agent/settings", { auto_off_hours: Number(v) })} options={hours} />
        </Row>
        <Row wide title="The other PC cannot connect?" desc="">
          <details><summary className="sub">What to check</summary>
            <p className="sub">Both PCs must be on the same Wi-Fi or network. The first time, Windows asks whether to allow Ala Eh! File Backup: allow it on private networks only. This app never opens your router or the internet.</p>
          </details>
        </Row>
      </Cluster>
      <Cluster title="What is shared">
        <Row wide title="Folders" desc="Only these folders can be read by a paired PC. Nothing else on this PC is visible, and this app's own data is never shared.">
          <PathList bare title="Folders to share" hint="" items={a.roots.map(r => r.path)} onChange={v => act("/api/agent/roots", { roots: v })} />
        </Row>
      </Cluster>
      <Cluster title="Pair a PC">
        <Row wide title="Pairing code" desc="Show a code here and type it on the other PC under PCs I back up. It works once, for 5 minutes, and stops after 5 wrong tries.">
          {a.pairing && left > 0
            ? <div className="pair"><p className="pair-code" aria-live="polite">{a.pairing.code}</p><p className="sub">Valid for {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")} more. This PC: {a.addresses[0] ?? ""} port {a.port}. Identity {a.fingerprint}.</p></div>
            : <div className="row"><button className="primary" disabled={!ready} onClick={() => act("/api/agent/pairing")}>Show a pairing code</button>
              {!ready && <span className="sub">{a.running ? "Choose a folder to share first." : "Turn sharing on first."}</span>}</div>}
        </Row>
      </Cluster>
      <Cluster title="PCs allowed to read this PC">
        {!a.clients.length && <div className="blank"><b>No PC is allowed yet.</b><span className="sub">A PC appears here after it pairs with a code.</span></div>}
        {a.clients.length > 0 && (
          <ul className="rows">
            {a.clients.map(c => (
              <li key={c.id} className="line"><span className="grow"><b>{c.name}</b><br /><span className="sub">Paired {c.added || "earlier"}</span></span>
                <button onClick={() => revoke(c.id, c.name)}>Remove</button></li>
            ))}
          </ul>
        )}
      </Cluster>
    </Group>
  );
}

/** Every request a paired PC made to this PC, newest first. */
function Activity({ a }: { a: Agent | null }) {
  return (
    <Group title="Activity" lead="What paired PCs read from this PC, newest first. Only while sharing is on.">
      {!a && <p className="sub">Loading…</p>}
      {a && !a.log.length && <div className="blank"><b>Nothing yet.</b><span className="sub">Requests from a paired PC show up here.</span></div>}
      {a && a.log.length > 0 && (
        <ul className="rows log">
          {a.log.map((l, i) => (
            <li key={i} className="line"><span className="sub num">{l.at}</span><span className="grow"><b>{l.who}</b> {l.what} <bdi className="sub">{l.path}</bdi></span><span className={"tag " + (l.status < 300 ? "backed_up" : "lv-warn")}>{l.status}</span></li>
          ))}
        </ul>
      )}
    </Group>
  );
}

export function Network() {
  const [section, setSection] = useStored<Section>("network.section", "peers");
  const [agent, setAgent] = useState<Agent | null>(null); const [agentErr, setAgentErr] = useState("");
  const [peers, setPeers] = useState<Peer[] | null>(null);
  const loadAgent = useCallback(async () => { try { setAgent(await api<Agent>("/api/agent")); } catch (e) { setAgentErr((e as Error).message); } }, []);
  const [checking, setChecking] = useState(false);
  const loadPeers = useCallback(async (check = false) => {
    if (check) setChecking(true);
    try { setPeers(await api<Peer[]>("/api/peers" + (check ? "?check=1" : ""))); } catch (e) { setAgentErr((e as Error).message); }
    setChecking(false);
  }, []);
  useEffect(() => { loadAgent(); loadPeers().then(() => loadPeers(true)); const t = setInterval(loadAgent, 3000); return () => clearInterval(t); }, [loadAgent, loadPeers]);   // show the list at once, then ask each PC
  useEffect(() => { if (section !== "peers") return; const t = setInterval(() => loadPeers(true), 15000); return () => clearInterval(t); }, [section, loadPeers]);
  const act = async (path: string, body?: unknown) => { try { setAgentErr(""); setAgent(await api<Agent>(path, "POST", body ?? {})); } catch (e) { setAgentErr((e as Error).message); } };
  const items = [
    { key: "peers", label: "PCs I back up", hint: peers ? (peers.length ? `${peers.length} paired${peers.some(p => p.state !== "online" && p.state !== "unknown") ? ", one away" : ""}` : "None yet") : undefined },
    { key: "share", label: "Share this PC", hint: agent ? (agent.running ? (agent.connected.length ? `On, ${agent.connected.length} connected` : "On") : "Off") : undefined },
    { key: "activity", label: "Activity", hint: agent?.log.length ? `${agent.log.length} recent` : undefined },
  ];
  return (
    <Panel items={items} current={section} onChange={k => setSection(k as Section)} label="Other PCs sections">
      {section === "peers" && <Peers peers={peers} reload={loadPeers} checking={checking} />}
      {section === "share" && <Share a={agent} act={act} err={agentErr} />}
      {section === "activity" && <Activity a={agent} />}
    </Panel>
  );
}
