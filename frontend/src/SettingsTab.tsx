import { useEffect, useRef, useState } from "react";
import { api, Settings, UpdateInfo, useStored } from "./api";
import { Cluster, Group, Panel, Row, Switch } from "./Panel";
import { PathList } from "./PathList";
import { UseDrive } from "./UseDrive";
import { Select, TimeField } from "./Select";
import { Density, ThemePref, useAppearance } from "./theme";

let saves: Promise<unknown> = Promise.resolve();   // saves run one after another, and loading waits for them

/** A number field that keeps what you type and only saves a real number. */
function NumField({ value, onCommit, max, label }: { value: number; onCommit: (n: number) => void; max?: number; label: string }) {
  const [raw, setRaw] = useState(String(value));
  useEffect(() => { setRaw(String(value)); }, [value]);
  const step = (d: number) => { const n = Math.max(0, (Number(raw) || 0) + d); setRaw(String(n)); onCommit(n); };
  return (
    <div className="num">
      <input type="number" aria-label={label} min={0} max={max} value={raw} onChange={e => { setRaw(e.target.value); if (e.target.value !== "" && !Number.isNaN(+e.target.value)) onCommit(Math.max(0, +e.target.value)); }} onBlur={() => setRaw(String(value))} />
      <button type="button" aria-label="Decrease" onClick={() => step(-1)}>-</button>
      <button type="button" aria-label="Increase" onClick={() => step(1)}>+</button>
    </div>
  );
}

const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
type Section = "backup" | "rules" | "schedule" | "alerts" | "app";

export function SettingsTab({ onSaved, appearance }: { onSaved: () => void; appearance: ReturnType<typeof useAppearance> }) {
  const [s, setS] = useState<Settings | null>(null); const [msg, setMsg] = useState(""); const [excl, setExcl] = useState(""); const [loadErr, setLoadErr] = useState(""); const [again, setAgain] = useState(0);
  const [section, setSection] = useStored<Section>("settings.section", "backup");
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
  const change = (n: Settings, e: string) => { latest.current = { s: n, excl: e }; dirty.current = true; setMsg("Saving…"); window.clearTimeout(timer.current); timer.current = window.setTimeout(send, 500); };
  useEffect(() => () => { window.clearTimeout(timer.current); send(); }, []); // save pending changes when leaving the tab
  // hooks must run before the early returns below, or React crashes (black screen) when the page finishes loading
  const [ver, setVer] = useState<UpdateInfo | null>(null);
  const [checking, setChecking] = useState(false);
  const checkNow = async () => {
    setChecking(true);
    try { setVer(await api<UpdateInfo>("/api/update?force=1")); } catch { /* shown as unchecked */ }
    setChecking(false);
  };
  useEffect(() => { api<UpdateInfo>("/api/update").then(setVer).catch(() => { /* offline */ }); }, []);
  useEffect(() => {                                                    // the name was changed from the dialog: show it here at once
    const f = (e: Event) => setS(c => c && { ...c, pc_name: String((e as CustomEvent).detail) });
    window.addEventListener("pc-renamed", f);
    return () => window.removeEventListener("pc-renamed", f);
  }, []);
  if (loadErr) return <section className="block"><p className="err">Could not load the settings: {loadErr}</p><div><button onClick={() => setAgain(n => n + 1)}>Try again</button></div></section>;
  if (!s) return (
    <div className="panel" aria-busy="true"><div className="panel-nav skel" aria-hidden="true" /><div className="panel-body"><p className="sub">Loading the settings…</p></div></div>
  );
  const set = (p: Partial<Settings>) => { const n = { ...s, ...p }; setS(n); change(n, excl); };
  const test = async () => {
    try { await send(); await api("/api/webhook/test", "POST"); setMsg("Test message sent."); }
    catch (e) { setMsg("Error: " + (e as Error).message); }
  };
  const saved = <span className={"savestat" + (msg.startsWith("Not saved") || msg.startsWith("Error") ? " bad" : "")} role="status">{msg || "Changes are saved automatically."}</span>;
  const items = [
    { key: "backup", label: "Backup", hint: s.destinations.length ? `${s.destinations.length} ${s.destinations.length === 1 ? "drive" : "drives"}` : "No drive yet" },
    { key: "rules", label: "Rules", hint: s.skip_junk ? "Junk skipped" : "Junk included" },
    { key: "schedule", label: "Schedule", hint: s.schedule.enabled ? `Daily at ${s.schedule.time}` : "Off" },
    { key: "alerts", label: "Alerts", hint: s.webhook ? "Webhook set" : "In the app only" },
    { key: "app", label: "App", hint: ver ? `Version ${ver.current}` : undefined },
  ];
  const day = (i: number, on: boolean) => set({ schedule: { ...s.schedule, days: on ? [...s.schedule.days, i].sort() : s.schedule.days.filter(x => x !== i) } });
  return (
    <Panel items={items} current={section} onChange={k => setSection(k as Section)} label="Settings sections">
      {section === "backup" && (
        <Group title="Backup" lead="Where backups go, and which files are looked at." aside={saved}>
          <Cluster title="Where backups go">
            <Row wide title="Backup drives" desc="Files are copied to every drive listed, for example an external disk. A drive is remembered by its serial number, so it is found again if Windows gives it another letter.">
              <PathList bare title="Backup drives" hint="" items={s.destinations} onChange={v => set({ destinations: v })} />
              {s.new_drives?.map(n => <UseDrive key={n.path} path={n.path} name={n.name} onDone={() => { setAgain(c => c + 1); onSaved(); }} />)}
            </Row>
            <Row title={`This PC: ${s.pc_name}`} desc="Backups go into a folder named after this PC on each drive, so many PCs can share one drive. Renaming also renames that folder on the drive.">
              <button onClick={() => window.dispatchEvent(new Event("rename-pc"))}>Rename this PC</button>
            </Row>
          </Cluster>
          <Cluster title="What gets looked at">
            <Row title="Scan the whole PC" desc={s.whole_pc ? `Every internal drive: ${s.scan_roots.join(", ")}. Then click Scan files.` : "Off: only the folders below are scanned."}>
              <Switch checked={s.whole_pc} onChange={v => set({ whole_pc: v })} label="Scan the whole PC" />
            </Row>
            {!s.whole_pc && (
              <Row wide title="Folders to scan" desc="Everything inside these folders is scanned.">
                {!s.sources.length && <p className="warn">No folders are chosen, so a scan would find nothing. Add one below or turn on Scan the whole PC.</p>}
                <PathList bare title="Folders to scan" hint="" items={s.sources} onChange={v => set({ sources: v })} />
              </Row>
            )}
            <Row title="When new files appear" desc="New files can wait for your decision, or be included straight away.">
              <Select label="When new files appear" value={s.new_files} onChange={v => set({ new_files: v as Settings["new_files"] })} options={[{ value: "review", label: "Hold them for review (recommended)" }, { value: "include", label: "Back them up automatically" }]} />
            </Row>
          </Cluster>
          <Cluster title="How files are copied">
            <Row title="Compare file contents" desc="On every backup, also check files whose size and date did not change. Slower, but catches an edit that kept both.">
              <Switch checked={s.deep_check} onChange={v => set({ deep_check: v })} label="Compare file contents on every backup" />
            </Row>
            <Row title="Share copies with other PCs" desc="When several PCs back up to the same drive, a file another PC already stored there is recognised in the scan and linked in the backup instead of being written again. It saves space and time. The other PC's copy is never changed.">
              <Switch checked={s.reuse_drive_copies} onChange={v => set({ reuse_drive_copies: v })} label="Share copies with other PCs on the same drive" />
            </Row>
            <Row title="Compress backups" desc="Saves space. Files are stored as .gz.">
              <Switch checked={s.compress} onChange={v => set({ compress: v })} label="Compress backups" />
            </Row>
            <Row title="Keep older versions" desc={s.keep_versions ? `When a file changes, the ${s.keep_versions} previous ${s.keep_versions === 1 ? "copy is" : "copies are"} kept on the drive, and you can restore one from Restore. This uses more space.` : "0 means a changed file simply replaces its backup. Set a number to keep that many older copies of each changed file."}>
              <NumField label="Older versions to keep" value={s.keep_versions} max={20} onCommit={n => set({ keep_versions: Math.min(20, n) })} />
            </Row>
          </Cluster>
        </Group>
      )}

      {section === "rules" && (
        <Group title="Rules" lead="What is never backed up." aside={saved}>
          <Cluster>
            <Row title="Skip junk" desc="Windows, program files, caches, node_modules, temp files and similar. Recommended.">
              <Switch checked={s.skip_junk} onChange={v => set({ skip_junk: v })} label="Skip Windows, program files, caches and other junk" />
            </Row>
            <Row wide title="Built-in junk rules" desc="The names the switch above skips.">
              <details><summary className="sub">Show the {s.junk_list.length} built-in rules</summary><p className="sub">{s.junk_list.join(", ")}</p></details>
            </Row>
            <Row wide title="Extra names to skip" desc="One per line. Wildcards are allowed. Start with / to match from the top of a drive.">
              <textarea aria-label="Extra names to skip" rows={5} value={excl} onChange={e => { setExcl(e.target.value); change(s, e.target.value); }} />
            </Row>
            <Row title="Largest file to back up" desc="In megabytes. Bigger files are skipped. 0 means no limit.">
              <NumField label="Largest file in megabytes" value={s.max_size_mb} onCommit={n => set({ max_size_mb: n })} />
            </Row>
          </Cluster>
        </Group>
      )}

      {section === "schedule" && (
        <Group title="Schedule" lead="Find new files on its own. Nothing is copied until you click Back up now." aside={saved}>
          <Cluster title="Daily scan">
            <Row title="Scan on a schedule" desc="The scan finds new files so they are waiting in New files. The app must be running at that time; if it was off, the scan runs when it starts that day.">
              <Switch checked={s.schedule.enabled} onChange={v => set({ schedule: { ...s.schedule, enabled: v } })} label="Scan on a schedule" />
            </Row>
            <Row off={!s.schedule.enabled} title="At what time">
              <TimeField label="Scan time" value={s.schedule.time} onChange={v => set({ schedule: { ...s.schedule, time: v } })} />
            </Row>
            <Row off={!s.schedule.enabled} wide title="On which days">
              <div className="days" role="group" aria-label="Days of the week">
                {days.map((d, i) => <label key={d} className="chip"><input type="checkbox" checked={s.schedule.days.includes(i)} onChange={e => day(i, e.target.checked)} /><span>{d}</span></label>)}
              </div>
            </Row>
          </Cluster>
          <Cluster title="Keep the list current">
            <Row title="Re-scan folders every" desc="In minutes, while the app is open. 0 turns it off.">
              <NumField label="Minutes between scans" value={s.auto_scan_minutes} onCommit={n => set({ auto_scan_minutes: n })} />
            </Row>
          </Cluster>
        </Group>
      )}

      {section === "alerts" && (
        <Group title="Alerts" lead="Warnings appear under the bell at the top of the app. A webhook sends them to your phone or chat as well." aside={saved}>
          <Cluster title="What to warn about">
            <Row title="Backup drive almost full" desc="Warn when a backup drive has less than this percent free. 0 turns it off.">
              <NumField label="Percent free that triggers a warning" value={s.alert_low_space_pct} max={90} onCommit={n => set({ alert_low_space_pct: Math.min(90, n) })} />
            </Row>
            <Row title="No recent backup" desc="Warn when files are chosen but nothing was backed up for this many days. 0 turns it off.">
              <NumField label="Days without a backup that trigger a warning" value={s.alert_stale_days} max={365} onCommit={n => set({ alert_stale_days: Math.min(365, n) })} />
            </Row>
            <Row title="Backup drive not plugged in" desc="Always on: you are warned when a backup drive cannot be found, and when what is waiting will not fit on it." />
          </Cluster>
          <Cluster title="Send them to a webhook">
            <Row wide title="Webhook" desc="Slack, Discord or any service that accepts JSON.">
              <div className="row">
                <input aria-label="Webhook URL" value={s.webhook} onChange={e => set({ webhook: e.target.value })} placeholder="https://" />
                <button onClick={test} disabled={!s.webhook}>Send test message</button>
              </div>
            </Row>
          </Cluster>
        </Group>
      )}

      {section === "app" && (
        <Group title="App" lead="This copy of the app, its version and where it keeps its data." aside={saved}>
          <Cluster title="Appearance">
            <Row title="Theme" desc="Dark is the default. Match Windows follows your system setting.">
              <Select label="Theme" value={appearance.theme} onChange={v => appearance.setTheme(v as ThemePref)} options={[{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }, { value: "system", label: "Match Windows" }]} />
            </Row>
            <Row title="Text size" desc="Compact makes the text and controls a little smaller to fit more on screen.">
              <Select label="Text size" value={appearance.density} onChange={v => appearance.setDensity(v as Density)} options={[{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }]} />
            </Row>
          </Cluster>
          <Cluster title="Updates">
            <Row title={`Version ${ver?.current ?? "..."}`} desc={ver?.error ? ver.error : ver?.available ? `Version ${ver.latest} is available.` : ver?.enabled === false ? "Update checks are off." : ver ? "This is the latest version." : "Checking…"}>
              <button onClick={checkNow} disabled={checking || ver?.enabled === false}>{checking ? "Checking…" : "Check for updates now"}</button>
            </Row>
            <Row title="Check for updates when the app opens" desc="Installed app only. Nothing is installed without you clicking Update now.">
              <Switch checked={s.update_check} onChange={v => set({ update_check: v })} label="Check GitHub for a newer version when the app opens" />
            </Row>
          </Cluster>
          <Cluster title="This installation">
            <Row wide title="Data folder" desc="Settings, the file list and history live here."><span className="path" title={s.data_dir}><bdi>{s.data_dir}</bdi></span></Row>
            <Row title="Password" desc={s.auth_required ? "A password is required to open the app." : "Set the BACKUP_PASSWORD environment variable to require one."}>
              <span className={"tag " + (s.auth_required ? "backed_up" : "")}>{s.auth_required ? "On" : "Off"}</span>
            </Row>
          </Cluster>
        </Group>
      )}
    </Panel>
  );
}
