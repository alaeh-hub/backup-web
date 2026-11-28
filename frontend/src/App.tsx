import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { api, eta, fmt, Job, Stats, UpdateInfo } from "./api";
import { Dashboard } from "./Dashboard";
import { Files } from "./Files";
import { Review } from "./Review";
import { Restore } from "./Restore";
import { Devices } from "./Devices";
import { Organize } from "./Organize";
import { Logs } from "./Logs";
import { Network } from "./Network";
import { SettingsTab } from "./SettingsTab";
import { Icon, Page, reduced } from "./ui";
import { DialogHost } from "./Dialog";
import { NamePc, namedMessage, NameResult } from "./NamePc";
import { PreviewHost } from "./Preview";
import { ShortcutsHost, openShortcuts } from "./Shortcuts";
import { clearCursor, cursorRow, focusSearch, modalOpen, moveCursor, onControl, openCursor, plain, toggleCursor, typingIn } from "./keys";
import { Notifications } from "./Notifications";
import { useAppearance } from "./theme";
import { animate } from "animejs";

type Tab = "dashboard" | "review" | "selected" | "files" | "restore" | "devices" | "organize" | "logs" | "settings" | "network";
const tabs: { key: Tab; label: string; icon: string; title: string; hint: string }[] = [
  { key: "dashboard", label: "Overview", icon: "overview", title: "Overview", hint: "What is backed up, what is waiting and where it goes." },
  { key: "review", label: "New files", icon: "inbox", title: "New files", hint: "Found since your last decision. Back them up or skip them." },
  { key: "selected", label: "Selected", icon: "check", title: "Selected for backup", hint: "Everything that will be copied on the next backup." },
  { key: "files", label: "Files", icon: "folder", title: "Files", hint: "Browse every scanned file and choose by folder, type or size." },
  { key: "restore", label: "Restore", icon: "restore", title: "Restore", hint: "Put backed up files back on this PC." },
  { key: "devices", label: "Devices", icon: "drive", title: "Devices", hint: "Every PC that has a folder on the backup drive." },
  { key: "organize", label: "Organize", icon: "organize", title: "Organize", hint: "Gather documents, pictures and videos into one sorted folder." },
  { key: "logs", label: "Logs", icon: "log", title: "Logs", hint: "Everything the tool has done, newest first." },
  { key: "settings", label: "Settings", icon: "settings", title: "Settings", hint: "Backup drives, rules, schedule and notifications." },
  { key: "network", label: "Other PCs", icon: "network", title: "Other PCs", hint: "Back up another PC over your network, or let one back up this PC." },
];
const idle: Job = { state: "idle", type: "", message: "", done: 0, total: 0 };
/** g then a letter goes to a screen: g o is Overview, g n New files, and so on. */
const CHORD: Record<string, Tab> = { o: "dashboard", n: "review", s: "selected", f: "files", r: "restore", d: "devices", z: "organize", l: "logs", t: "settings", p: "network" };

function Login({ onOk }: { onOk: () => void }) {
  const [pw, setPw] = useState(""); const [err, setErr] = useState("");
  const go = async (e: React.FormEvent) => { e.preventDefault(); try { await api("/api/auth/login", "POST", { password: pw }); onOk(); } catch (x) { setErr((x as Error).message); } };
  return (
    <main className="login">
      <form onSubmit={go}>
        <img className="logo" src="/static/ala-eh-logo.png" alt="Ala Eh! Food Products" width={72} height={72} />
        <h1>File Backup</h1>
        <label>Password<input type="password" autoFocus value={pw} onChange={e => setPw(e.target.value)} /></label>
        {err && <p className="err">{err}</p>}
        <div><button className="primary" type="submit">Sign in</button></div>
      </form>
    </main>
  );
}

export default function App() {
  const [auth, setAuth] = useState<"loading" | "login" | "ok" | "error">("loading");
  const [tab, setTab] = useState<Tab>("dashboard");
  // Where the person has been, so Alt+Left and the mouse back button can walk back (and forward again).
  const hist = useRef<{ stack: Tab[]; at: number }>({ stack: ["dashboard"], at: 0 });
  const goTab = useCallback((k: Tab) => {
    const h = hist.current;
    if (h.stack[h.at] === k) return;
    h.stack = [...h.stack.slice(0, h.at + 1), k].slice(-40);
    h.at = h.stack.length - 1;
    setTab(k);
  }, []);
  const stepTab = useCallback((d: number) => {
    const h = hist.current, at = h.at + d;
    if (at < 0 || at >= h.stack.length) return;
    h.at = at;
    setTab(h.stack[at]);
  }, []);
  const [stats, setStats] = useState<Stats | null>(null);
  const [job, setJob] = useState<Job>(idle);
  const [msg, setMsg] = useState("");
  const [tick, setTick] = useState(0);
  const [upd, setUpd] = useState<UpdateInfo | null>(null);
  const [updating, setUpdating] = useState(false);
  const [updErr, setUpdErr] = useState("");
  const [updHidden, setUpdHidden] = useState(false);
  const [named, setNamed] = useState(false);                      // the name was just saved: hide the first-run dialog before the next stats arrive
  const [renaming, setRenaming] = useState(false);
  useEffect(() => { const open = () => setRenaming(true); window.addEventListener("rename-pc", open); return () => window.removeEventListener("rename-pc", open); }, []);
  const prev = useRef<Job["state"]>("idle");
  const logo = useRef<HTMLImageElement>(null);
  const live = useRef({ backup: () => {}, scan: () => {}, theme: () => {}, refresh: () => {} });      // the latest actions, for the key handler

  const appearance = useAppearance();
  const [appVersion, setAppVersion] = useState("");
  const checkAuth = useCallback(() => api<{ required: boolean; authed: boolean; version?: string }>("/api/auth/status").then(a => { setAppVersion(a.version ?? ""); setAuth(a.authed ? "ok" : "login"); }).catch(() => setAuth("error")), []);
  useEffect(() => { checkAuth(); const f = () => setAuth("login"); window.addEventListener("unauth", f); return () => window.removeEventListener("unauth", f); }, [checkAuth]);

  const loadStats = useCallback(async () => { try { setStats(await api<Stats>("/api/stats")); } catch { /* the login screen handles 401 */ } }, []);
  const pollJob = useCallback(async () => { try { setJob(await api<Job>("/api/job")); } catch { /* ignore */ } }, []);
  useEffect(() => { if (auth === "ok") api<UpdateInfo>("/api/update").then(setUpd).catch(() => { /* offline: no banner */ }); }, [auth]);
  const installUpdate = async () => {
    setUpdating(true); setUpdErr("");
    try { await api("/api/update/install", "POST"); }       // the app closes and reopens by itself
    catch (e) { setUpdErr((e as Error).message); setUpdating(false); }
  };
  useEffect(() => {
    if (auth !== "ok") return;
    loadStats(); pollJob();
    const t = setInterval(pollJob, 1000);
    const s = setInterval(loadStats, 10000);
    return () => { clearInterval(t); clearInterval(s); };
  }, [auth, loadStats, pollJob]);
  useEffect(() => {
    if (prev.current === "running" && job.state !== "running") { setMsg(job.message); loadStats(); setTick(t => t + 1); }
    prev.current = job.state;
  }, [job, loadStats]);
  // The logo turns once when the app opens (anime.js).
  useEffect(() => {
    if (auth !== "ok" || !logo.current || reduced()) return;
    const a = animate(logo.current, { rotate: [-140, 0], scale: [0.6, 1], duration: 1100, ease: "outElastic(1, .7)" });
    return () => { a.revert(); };
  }, [auth]);

  // Keyboard and mouse buttons for the whole app. The list of them is in Shortcuts.tsx (press ?).
  useEffect(() => {
    if (auth !== "ok") return;
    let chord = 0;                                                   // when g was pressed, for g then a letter
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;                                // a field or menu already used this key
      const t = e.target, key = e.key, L = live.current, mod = e.ctrlKey || e.metaKey;
      if (key === "F1" || (key === "?" && !typingIn(t))) { e.preventDefault(); openShortcuts(); return; }
      if (modalOpen()) return;                                       // a dialog or the preview has its own keys
      if (mod && key === "Enter") { e.preventDefault(); L.backup(); return; }
      if (mod && e.shiftKey && key.toLowerCase() === "s") { e.preventDefault(); L.scan(); return; }
      if (mod && !e.shiftKey && key.toLowerCase() === "k") { e.preventDefault(); focusSearch(); return; }
      if (e.altKey && !mod && (key === "ArrowLeft" || key === "ArrowRight")) { e.preventDefault(); stepTab(key === "ArrowLeft" ? -1 : 1); return; }
      if (typingIn(t)) { if (key === "Escape") (t as HTMLElement).blur(); return; }
      if (!plain(e)) return;
      if (chord && Date.now() - chord < 1200) {
        chord = 0;
        const k = CHORD[key.toLowerCase()];
        if (k) { e.preventDefault(); goTab(k); return; }
      }
      if (key === "g") { chord = Date.now(); return; }
      if (key.length === 1 && key >= "0" && key <= "9") {
        const n = key === "0" ? 10 : Number(key);
        if (n <= tabs.length) { goTab(tabs[n - 1].key); return; }
      }
      const row = cursorRow();
      if (key === "/") { e.preventDefault(); focusSearch(); }
      else if (key === "j") { e.preventDefault(); moveCursor(1); }
      else if (key === "k") { e.preventDefault(); moveCursor(-1); }
      else if (row && key === "Home") { e.preventDefault(); moveCursor("first"); }
      else if (row && key === "End") { e.preventDefault(); moveCursor("last"); }
      else if (row && key === "Enter" && !onControl(t)) { e.preventDefault(); openCursor(); }
      else if (row && key === "x") { e.preventDefault(); toggleCursor(); }
      else if (key === "r") { e.preventDefault(); L.refresh(); }
      else if (key === "t") { e.preventDefault(); L.theme(); }
      else if (key === "Escape") clearCursor();
    };
    const onMouse = (e: MouseEvent) => {                              // the mouse's back and forward buttons walk back through the screens
      if (e.button !== 3 && e.button !== 4) return;
      if (modalOpen()) return;
      e.preventDefault();
      if (e.type === "mouseup") stepTab(e.button === 3 ? -1 : 1);
    };
    const changed = () => { live.current.refresh(); };                // the preview chose or skipped a file: lists and counts catch up
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onMouse); window.addEventListener("mouseup", onMouse); window.addEventListener("auxclick", onMouse);
    window.addEventListener("files-changed", changed);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onMouse); window.removeEventListener("mouseup", onMouse); window.removeEventListener("auxclick", onMouse);
      window.removeEventListener("files-changed", changed);
    };
  }, [auth, goTab, stepTab]);

  useEffect(() => {
    document.querySelector('.nav [aria-current="page"]')?.scrollIntoView({ inline: "center", block: "nearest", behavior: reduced() ? "auto" : "smooth" });
  }, [tab, auth]);

  const busy = job.state === "running";
  const start = async (path: string) => { setMsg(""); try { await api(path, "POST"); await pollJob(); } catch (e) { setMsg("Error: " + (e as Error).message); } };
  const onJob = async () => { setMsg(""); await pollJob(); };
  live.current = {
    backup: () => { if (!busy && stats?.files) void start("/api/backup"); },
    scan: () => { if (!busy) void start("/api/scan"); },
    theme: () => appearance.setTheme(appearance.mode === "light" ? "dark" : "light"),
    refresh: () => { void loadStats(); setTick(t => t + 1); },
  };

  if (auth === "loading") return null;
  if (auth === "error") return (
    <main className="login"><form onSubmit={e => { e.preventDefault(); setAuth("loading"); checkAuth(); }}>
      <h1>File Backup</h1><p className="err">The backup service did not answer. It may still be starting.</p>
      <div><button className="primary" type="submit">Try again</button></div>
    </form></main>
  );
  if (auth === "login") return <Login onOk={() => setAuth("ok")} />;

  const cur = tabs.find(t => t.key === tab)!;
  const badge = (k: Tab) => k === "review" ? stats?.review_files : k === "selected" ? stats?.selected_files : 0;
  const first = stats?.destinations[0];
  const firstRun = !!stats && stats.pc_named === false && !named;

  return (
    <MotionConfig reducedMotion="user">
      <DialogHost />
      <AnimatePresence>
        {(firstRun || renaming) && stats && (
          <NamePc key="name-pc" mode={firstRun ? "first" : "rename"} current={stats.pc_name} drive={stats.destinations[0]?.path}
            onCancel={() => setRenaming(false)}
            onDone={(r: NameResult) => {
              setMsg(namedMessage(r, firstRun)); setNamed(true); setRenaming(false); loadStats();
              window.dispatchEvent(new CustomEvent("pc-renamed", { detail: r.name }));
            }} />
        )}
      </AnimatePresence>
      <ShortcutsHost />
      <PreviewHost />
      <div className="app">
        <aside className="side">
          <button className="brand" onClick={() => goTab("dashboard")} aria-label="File Backup, go to the overview">
            <img ref={logo} className="logo" src="/static/ala-eh-logo.png" alt="" width={44} height={44} />
            <span className="brand-text"><span className="brand-name">File Backup</span><span className="brand-sub">Ala Eh! Food Products</span></span>
          </button>
          <nav className="nav" aria-label="Sections">
            {tabs.map((t, i) => {
              const n = badge(t.key);
              return (
                <div key={t.key} className="nav-item">
                  {(i === 0 || i === 4) && <span className="nav-label">{i === 0 ? "Backup" : "Tools"}</span>}
                  <button aria-current={tab === t.key ? "page" : undefined} title={`${t.label} (${i + 1}, or g then ${Object.keys(CHORD).find(k => CHORD[k] === t.key)})`} onClick={() => goTab(t.key)}>
                    {tab === t.key && <motion.span layoutId="nav-pill" className="nav-pill" transition={{ type: "spring", stiffness: 520, damping: 40 }} />}
                    <Icon name={t.icon} /><span className="nav-text">{t.label}</span>
                    {!!n && <span className={"badge" + (t.key === "selected" ? " quiet" : "")}>{n > 999 ? "999+" : n.toLocaleString()}</span>}
                  </button>
                </div>
              );
            })}
          </nav>
          <div className="side-foot">
            <div className="sf-pc"><Icon name="drive" /><span><span className="k">This PC</span><b>{stats?.pc_name ?? "..."}</b></span></div>
            <div className="sf-drive">
              <span className="k">Backup drive</span>
              {first ? (
                <>
                  <span className="sf-path" title={first.path}><bdi>{first.path}</bdi></span>
                  {first.total ? (
                    <>
                      <div className="meter slim" aria-hidden="true"><i style={{ transform: `scaleX(${1 - (first.free ?? 0) / first.total})` }} /></div>
                      <span className="sub"><b>{fmt(first.free)}</b> free of {fmt(first.total)}</span>
                    </>
                  ) : <span className="warn">Drive not reachable</span>}
                </>
              ) : <span className="sub">No backup drive set</span>}
            </div>
            <dl className="sf-facts">
              <div><dt>Last backup</dt><dd>{stats?.last_backup ?? "Never"}</dd></div>
              {appVersion && <div><dt>Version</dt><dd>{appVersion}</dd></div>}
            </dl>
            {stats?.sharing && <span className="sf-share">Sharing on{stats.sharing_connected ? `, ${stats.sharing_connected} connected` : ""}</span>}
          </div>
        </aside>

        <div className="main">
          <header className={"head" + (busy ? " busy" : "") + (busy && job.total <= 0 ? " indet" : "")} style={{ ["--p" as string]: job.total > 0 ? Math.min(job.done / job.total, 1) : 0 }}>
            <div className="head-title">
              <h1>{cur.title}</h1>
              <AnimatePresence mode="wait" initial={false}>
                <motion.p key={busy ? "job" : tab} className={busy ? "head-job" : undefined} title={busy ? job.message : undefined} role={busy ? "status" : undefined}
                  initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.16 }}>
                  {busy ? <><b>{job.type.charAt(0).toUpperCase() + job.type.slice(1)}:</b> {eta(job) || job.message}</> : cur.hint}
                </motion.p>
              </AnimatePresence>
            </div>
            <div className="head-actions">
              <Notifications alerts={stats?.alerts ?? []} go={t => goTab(t as Tab)} />
              <button aria-label={appearance.mode === "light" ? "Switch to dark mode" : "Switch to light mode"} title={appearance.mode === "light" ? "Dark mode (t)" : "Light mode (t)"} onClick={() => appearance.setTheme(appearance.mode === "light" ? "dark" : "light")}><Icon name={appearance.mode === "light" ? "moon" : "sun"} /></button>
              <button aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)" onClick={openShortcuts}><Icon name="keyboard" /></button>
              {busy && <button onClick={() => api("/api/job/cancel", "POST").catch(e => setMsg("Error: " + (e as Error).message))}><Icon name="cancel" /><span className="hide-sm">Cancel</span></button>}
              <button aria-label="Scan files" title="Scan files (Ctrl+Shift+S)" onClick={() => start("/api/scan")} disabled={busy}><Icon name="scan" /><span className="hide-sm">Scan files</span></button>
              <button className="primary" title="Back up now (Ctrl+Enter)" onClick={() => start("/api/backup")} disabled={busy || !stats?.files}><Icon name="backup" />Back up<span className="hide-sm"> now{stats?.pending_bytes ? ` (${fmt(stats.pending_bytes)})` : ""}</span></button>
            </div>
          </header>

          <main className="content">
            {stats?.offline_pcs?.map(o => (
              <div key={o.id} className="update away" role="status">
                <p><b>{o.name} cannot be reached.</b> <span className="sub">{o.text} Its {o.files.toLocaleString()} files ({fmt(o.bytes)}) are from the last scan and cannot be backed up until it is back.</span></p>
                <div className="update-actions"><button onClick={() => goTab("network")}>Open Other PCs</button></div>
              </div>
            ))}
            {upd?.available && !updHidden && (
              <div className="update" role="status">
                <p><b>Update available: version {upd.latest}</b> <span className="sub">(you have {upd.current})</span>
                  {updating ? " Downloading and installing... the app will reopen by itself." : ""}
                  {updErr && <span className="err"> {updErr}</span>}</p>
                <div className="update-actions">
                  {upd.can_install
                    ? <button className="primary" onClick={installUpdate} disabled={updating || busy} title={busy ? "Wait for the running job to finish" : undefined}>{updating ? "Updating..." : "Update now"}</button>
                    : <a className="btn" href={upd.page} target="_blank" rel="noreferrer">See what is new</a>}
                  {!updating && <button className="quiet" onClick={() => setUpdHidden(true)}>Later</button>}
                </div>
              </div>
            )}
            {!busy && msg && <p className="msg" role="status">{msg}</p>}
            <Page key={["review", "selected", "files", "restore"].includes(tab) ? tab + ":" + tick : tab}>
              {tab === "dashboard" && <Dashboard stats={stats} busy={busy} jobType={job.type} go={goTab} onJob={onJob} />}
              {tab === "review" && <Review onChange={loadStats} />}
              {tab === "selected" && <Review mode="selected" onChange={loadStats} />}
              {tab === "files" && <Files onChange={loadStats} />}
              {tab === "restore" && <Restore onJob={onJob} />}
              {tab === "devices" && <Devices />}
              {tab === "organize" && <Organize busy={busy} onJob={onJob} />}
              {tab === "logs" && <Logs tick={tick} />}
              {tab === "settings" && <SettingsTab onSaved={loadStats} appearance={appearance} />}
              {tab === "network" && <Network />}
            </Page>
          </main>
        </div>
      </div>
    </MotionConfig>
  );
}
