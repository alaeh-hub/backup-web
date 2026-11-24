import { useEffect, useRef, useState } from "react";
import { api, Settings } from "./api";
import { PathList } from "./PathList";
import { Select, TimeField } from "./Select";

let saves: Promise<unknown> = Promise.resolve();   // saves run one after another, and loading waits for them

/** A number field that keeps what you type and only saves a real number. */
function NumField({ value, onCommit, max }: { value: number; onCommit: (n: number) => void; max?: number }) {
  const [raw, setRaw] = useState(String(value));
  useEffect(() => { setRaw(String(value)); }, [value]);
  const step = (d: number) => { const n = Math.max(0, (Number(raw) || 0) + d); setRaw(String(n)); onCommit(n); };
  return (
    <div className="num">
      <input type="number" min={0} max={max} value={raw} onChange={e => { setRaw(e.target.value); if (e.target.value !== "" && !Number.isNaN(+e.target.value)) onCommit(Math.max(0, +e.target.value)); }} onBlur={() => setRaw(String(value))} />
      <button type="button" aria-label="Decrease" onClick={() => step(-1)}>-</button>
      <button type="button" aria-label="Increase" onClick={() => step(1)}>+</button>
    </div>
  );
}

const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function SettingsTab({ onSaved }: { onSaved: () => void }) {
  const [s, setS] = useState<Settings | null>(null); const [msg, setMsg] = useState(""); const [excl, setExcl] = useState(""); const [loadErr, setLoadErr] = useState(""); const [again, setAgain] = useState(0);
  const latest = useRef<{ s: Settings; excl: string } | null>(null); const dirty = useRef(false); const timer = useRef<number>();
  useEffect(() => {
    setLoadErr("");
    saves.then(() => api<Settings>("/api/settings")).then(x => { setS(x); setExcl(x.excludes.join("\n")); }).catch(e => setLoadErr((e as Error).message));
  }, [again]);
  const send = async () => {
    const l = latest.current; if (!l || !dirty.current) return;
    dirty.current = false;
    const job = saves.then(() => api<Settings>("/api/settings", "POST", { ...l.s, excludes: l.excl.split("\n") }));
    saves = job.catch(() => undefined);
    try { const x = await job; setS(c => c && { ...c, scan_roots: x.scan_roots }); setMsg("Saved automatically."); onSaved(); }
    catch (e) { dirty.current = true; setMsg("Not saved: " + (e as Error).message); }
  };
  const change = (n: Settings, e: string) => { latest.current = { s: n, excl: e }; dirty.current = true; setMsg("Saving..."); window.clearTimeout(timer.current); timer.current = window.setTimeout(send, 500); };
  useEffect(() => () => { window.clearTimeout(timer.current); send(); }, []); // save pending changes when leaving the tab
  if (loadErr) return <section className="block"><p className="err">Could not load the settings: {loadErr}</p><div><button onClick={() => setAgain(n => n + 1)}>Try again</button></div></section>;
  if (!s) return <p className="sub">Loading...</p>;
  const set = (p: Partial<Settings>) => { const n = { ...s, ...p }; setS(n); change(n, excl); };
  const test = async () => {
    try { await send(); await api("/api/webhook/test", "POST"); setMsg("Test message sent."); }
    catch (e) { setMsg("Error: " + (e as Error).message); }
  };
  return (
    <>
      <section className="block">
        <h2>What to scan</h2>
        <label className="check"><input type="checkbox" checked={s.whole_pc} onChange={e => set({ whole_pc: e.target.checked })} /> Scan the whole PC (every internal drive{s.whole_pc ? ": " + s.scan_roots.join(", ") : ""})</label>
        <p className="sub">Then click Scan files. Turn this off to scan only chosen folders.</p>
      </section>
      {!s.whole_pc && !s.sources.length && <p className="warn">No folders are chosen, so a scan would find nothing. Add a folder below or turn on Scan the whole PC.</p>}
      {!s.whole_pc && <PathList title="Folders to scan" hint="Everything inside these folders is scanned." items={s.sources} onChange={v => set({ sources: v })} />}
      <PathList title="Backup drives" hint="Files are copied to every drive listed, for example an external disk. The drive is remembered by its serial number, so it is found again if Windows gives it another letter." items={s.destinations} onChange={v => set({ destinations: v })} />
      <section className="block">
        <h2>This PC: {s.pc_name}</h2>
        <p className="sub">Backups go into a folder named after this PC on each drive, so many PCs can share one drive.</p>
        <label className="check"><input type="checkbox" checked={s.skip_junk} onChange={e => set({ skip_junk: e.target.checked })} /> Skip Windows, program files, caches, node_modules, temp and other junk (recommended)</label>
        <details><summary className="sub">Show the built-in junk rules</summary><p className="sub">{s.junk_list.join(", ")}</p></details>
        <label>When new files appear<Select label="When new files appear" value={s.new_files} onChange={v => set({ new_files: v as Settings["new_files"] })} options={[{ value: "review", label: "Hold them for review (recommended)" }, { value: "include", label: "Back them up automatically" }]} /></label>
      </section>
      <section className="block">
        <h2>Rules</h2>
        <label>Extra names to skip, one per line (wildcards allowed; start with / to match from the top of a drive)<textarea rows={5} value={excl} onChange={e => { setExcl(e.target.value); change(s, e.target.value); }} /></label>
        <div className="fields">
          <label>Skip files larger than (MB, 0 for no limit)<NumField value={s.max_size_mb} onCommit={n => set({ max_size_mb: n })} /></label>
        </div>
        <label className="check"><input type="checkbox" checked={s.compress} onChange={e => set({ compress: e.target.checked })} /> Compress backups (saves space, files are stored as .gz)</label>
      </section>
      <section className="block">
        <h2>Scheduled scan</h2>
        <label className="check"><input type="checkbox" checked={s.schedule.enabled} onChange={e => set({ schedule: { ...s.schedule, enabled: e.target.checked } })} /> Scan on a schedule (nothing is copied)</label>
        <div className="fields">
          <label>Time<TimeField value={s.schedule.time} onChange={v => set({ schedule: { ...s.schedule, time: v } })} /></label>
          <label>Re-scan folders every (minutes, 0 for off)<NumField value={s.auto_scan_minutes} onCommit={n => set({ auto_scan_minutes: n })} /></label>
        </div>
        <div className="days">{days.map((d, i) => <label key={d} className="check"><input type="checkbox" checked={s.schedule.days.includes(i)} onChange={e => set({ schedule: { ...s.schedule, days: e.target.checked ? [...s.schedule.days, i] : s.schedule.days.filter(x => x !== i) } })} /> {d}</label>)}</div>
        <p className="sub">The scan finds new files so they are waiting in New files before you back up. Nothing is copied to the backup drive until you click Back up now. The tool must be running at that time. If it was off, the scan runs when it starts that day.</p>
      </section>
      <section className="block">
        <h2>Notifications</h2>
        <label>Webhook URL (Slack, Discord or any service that accepts JSON)<input value={s.webhook} onChange={e => set({ webhook: e.target.value })} placeholder="https://" /></label>
        <div><button onClick={test} disabled={!s.webhook}>Send test message</button></div>
      </section>
      <section className="block">
        <h2>Updates</h2>
        <label className="check"><input type="checkbox" checked={s.update_check} onChange={e => set({ update_check: e.target.checked })} /> Check GitHub for a newer version when the app opens (installed app only)</label>
        <p className="sub">Nothing is installed without you clicking Update now.</p>
      </section>
      <section className="block">
        <p className="sub">Changes are saved automatically.</p>
        {msg && <p className="msg" role="status">{msg}</p>}
        <p className="sub">Tool data is stored in {s.data_dir}. {s.auth_required ? "Password protected." : "Set the BACKUP_PASSWORD environment variable to require a password."}</p>
      </section>
    </>
  );
}
