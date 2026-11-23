import { api, fmt, Stats } from "./api";
import { CountUp, Icon, useGrow } from "./ui";
import { tell } from "./Dialog";

type Go = (t: "settings" | "files" | "review" | "selected") => void;
const LEG: Record<string, string> = { done: "var(--color-ink-2)", pend: "var(--color-accent)", review: "var(--color-review)", skip: "var(--color-skip)" };

export function Dashboard({ stats, busy, go, onJob }: { stats: Stats | null; busy: boolean; go: Go; onJob: () => void }) {
  const peak = stats ? Math.max(...stats.history.map(h => h.bytes), 1) : 1;
  const bar = useGrow(".ledger-bar i", "x", [stats?.total_bytes, stats?.backed_bytes, stats?.pending_bytes]);
  const chart = useGrow(".bar-col i", "y", [stats?.history.length, peak]);

  if (!stats) return <section className="block" aria-busy="true"><p className="sub">Loading...</p></section>;
  if (!stats.files) return (
    <section className="block empty-state">
      <h2>Nothing scanned yet</h2>
      <p className="sub">Pick the drive to back up to in Settings, then click Scan files. The whole PC is scanned by default.</p>
      <button className="primary" onClick={() => go("settings")}>Open Settings</button>
    </section>
  );
  const allDone = stats.backed_files > 0 && stats.pending_files === 0 && stats.review_files === 0;
  const verify = async () => { try { await api("/api/verify", "POST"); onJob(); } catch (e) { await tell("Could not start the check: " + (e as Error).message); } };
  const parts = [
    { key: "done", label: "Backed up", bytes: stats.backed_bytes, files: stats.backed_files, cls: "seg-done", go: "selected" as const },
    { key: "pend", label: "Waiting to back up", bytes: stats.pending_bytes, files: stats.pending_files, cls: "seg-pend", go: "selected" as const },
    { key: "review", label: "To review", bytes: stats.review_bytes, files: stats.review_files, cls: "seg-review", go: "review" as const },
    { key: "skip", label: "Skipped", bytes: stats.skipped_bytes, files: stats.skipped_files, cls: "seg-skip", go: "files" as const },
  ];
  return (
    <>
      <section className="block ledger" aria-label="Where every scanned file stands">
        <div className="ledger-top">
          <div>
            <span className="k">Scanned on {stats.pc_name}</span>
            <CountUp className="big" value={stats.total_bytes} format={fmt} />
          </div>
          <div className="ledger-meta">
            <span><b>{stats.files.toLocaleString()}</b> files</span>
            <span>Last backup: {stats.last_backup ?? "never"}</span>
            <span>{stats.next_run ? "Next: " + stats.next_run : "No schedule set"}</span>
          </div>
        </div>
        {allDone && <p className="all-done" role="status"><Icon name="check" />Everything is backed up. Nothing new or changed since the last scan.</p>}
        <div className="ledger-bar" ref={bar} role="img" aria-label={parts.map(p => `${p.label} ${fmt(p.bytes)}`).join(", ")}>
          {parts.map(p => <i key={p.key} className={p.cls + (p.bytes ? " has" : "")} style={{ flexGrow: p.bytes }} />)}
        </div>
        <div className="ledger-legend">
          {parts.map(p => (
            <button key={p.key} className="leg" style={{ ["--leg" as string]: LEG[p.key] }} onClick={() => go(p.go)}>
              <span className="k">{p.label}</span><strong>{fmt(p.bytes)}</strong><span className="sub">{p.files.toLocaleString()} files</span>
            </button>
          ))}
        </div>
      </section>

      <div className="two">
        <section className="block">
          <h2>Backup drives</h2>
          <ul className="rows">
            {stats.destinations.map(d => {
              const used = d.total ? 1 - (d.free ?? 0) / d.total : 0;
              const low = d.free !== null && stats.pending_bytes > d.free;
              return (
                <li key={d.path} className="gauge">
                  <div className="line"><Icon name="drive" /><span className="path" title={d.path}><bdi>{d.path}</bdi></span>{d.label && <span className="sub">{d.label}</span>}</div>
                  <span className={low ? "warn" : "sub"}>{d.total ? `${fmt(d.free)} free of ${fmt(d.total)}` : "Not reachable"}{low ? ". Not enough room for what is waiting." : ""}</span>
                  {d.total ? <div className="meter" aria-hidden="true"><i style={{ transform: `scaleX(${used})` }} /></div> : null}
                </li>
              );
            })}
            {!stats.destinations.length && <li className="sub">No backup drive yet. Add one in Settings.</li>}
          </ul>
          <div><button onClick={verify} disabled={busy}>Verify backed up copies</button></div>
        </section>
        <section className="block">
          <h2>Backed up per day</h2>
          <div className="chart" ref={chart} role="img" aria-label="Data backed up in the last 14 days">
            {stats.history.map(h => (
              <div key={h.day} className="bar-col" title={`${h.day}: ${fmt(h.bytes)}`}>
                <div className="bar-wrap"><i className={h.bytes ? "" : "zero"} style={{ height: h.bytes ? `${Math.max((h.bytes / peak) * 100, 4)}%` : undefined }} /></div>
                <span>{h.day.slice(3)}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="two">
        <section className="block">
          <h2>Largest folders</h2>
          <ul className="rows">{stats.largest_folders.map(f => <li key={f.name} className="line"><Icon name="folder" /><span className="path" title={f.name}><bdi>{f.name}</bdi></span><strong>{fmt(f.size)}</strong></li>)}</ul>
        </section>
        <section className="block">
          <h2>Largest files</h2>
          <ul className="rows">{stats.largest_files.map(f => <li key={f.path} className="line"><Icon name="file" /><span className="path" title={f.path}><bdi>{f.path}</bdi></span><strong>{fmt(f.size)}</strong></li>)}</ul>
        </section>
      </div>
    </>
  );
}
