import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { api, eta, fmt, Job, Stats } from "./api";
import { Dashboard } from "./Dashboard";
import { Files } from "./Files";
import { Review } from "./Review";
import { Restore } from "./Restore";
import { Devices } from "./Devices";
import { Organize } from "./Organize";
import { Logs } from "./Logs";
import { SettingsTab } from "./SettingsTab";
import { Icon, Page, reduced } from "./ui";
import { DialogHost } from "./Dialog";
import { animate } from "animejs";

type Tab = "dashboard" | "review" | "selected" | "files" | "restore" | "devices" | "organize" | "logs" | "settings";
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
];
/** Where the Windows installer is published (GitHub Releases: attach AlaEhBackup-Setup.exe to the latest release). */
const INSTALLER_URL = "https://github.com/alaeh-hub/backup-web/releases/latest/download/AlaEhBackup-Setup.exe";
/** The installer is only offered on the hosted site; the installed app already runs on this PC. */
const HOSTED = !["localhost", "127.0.0.1", "::1", "[::1]"].includes(location.hostname);
const idle: Job = { state: "idle", type: "", message: "", done: 0, total: 0 };

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
  const [stats, setStats] = useState<Stats | null>(null);
  const [job, setJob] = useState<Job>(idle);
  const [msg, setMsg] = useState("");
  const [tick, setTick] = useState(0);
  const prev = useRef<Job["state"]>("idle");
  const logo = useRef<HTMLImageElement>(null);

  const checkAuth = useCallback(() => api<{ required: boolean; authed: boolean }>("/api/auth/status").then(a => setAuth(a.authed ? "ok" : "login")).catch(() => setAuth("error")), []);
  useEffect(() => { checkAuth(); const f = () => setAuth("login"); window.addEventListener("unauth", f); return () => window.removeEventListener("unauth", f); }, [checkAuth]);

  const loadStats = useCallback(async () => { try { setStats(await api<Stats>("/api/stats")); } catch { /* the login screen handles 401 */ } }, []);
  const pollJob = useCallback(async () => { try { setJob(await api<Job>("/api/job")); } catch { /* ignore */ } }, []);
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

  useEffect(() => {
    if (auth !== "ok") return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
      const n = Number(e.key);
      if (n >= 1 && n <= tabs.length) setTab(tabs[n - 1].key);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [auth]);

  useEffect(() => {
    document.querySelector('.nav [aria-current="page"]')?.scrollIntoView({ inline: "center", block: "nearest", behavior: reduced() ? "auto" : "smooth" });
  }, [tab, auth]);

  const busy = job.state === "running";
  const start = async (path: string) => { setMsg(""); try { await api(path, "POST"); await pollJob(); } catch (e) { setMsg("Error: " + (e as Error).message); } };
  const onJob = async () => { setMsg(""); await pollJob(); };

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

  return (
    <MotionConfig reducedMotion="user">
      <DialogHost />
      <div className="app">
        <aside className="side">
          <button className="brand" onClick={() => setTab("dashboard")} aria-label="File Backup, go to the overview">
            <img ref={logo} className="logo" src="/static/ala-eh-logo.png" alt="" width={44} height={44} />
            <span className="brand-text"><span className="brand-name">File Backup</span><span className="brand-sub">Ala Eh! Food Products</span></span>
          </button>
          <nav className="nav" aria-label="Sections">
            {tabs.map((t, i) => {
              const n = badge(t.key);
              return (
                <div key={t.key} className="nav-item">
                  {(i === 0 || i === 4) && <span className="nav-label">{i === 0 ? "Backup" : "Tools"}</span>}
                  <button aria-current={tab === t.key ? "page" : undefined} title={`${t.label} (${i + 1})`} onClick={() => setTab(t.key)}>
                    {tab === t.key && <motion.span layoutId="nav-pill" className="nav-pill" transition={{ type: "spring", stiffness: 520, damping: 40 }} />}
                    <Icon name={t.icon} /><span className="nav-text">{t.label}</span>
                    {!!n && <span className={"badge" + (t.key === "selected" ? " quiet" : "")}>{n > 999 ? "999+" : n.toLocaleString()}</span>}
                  </button>
                </div>
              );
            })}
          </nav>
          <div className="side-foot">
            <span className="k">This PC</span>
            <b>{stats?.pc_name ?? "..."}</b>
            {first ? (
              <>
                <span className="sub wrap">{first.path}</span>
                {first.total ? <div className="meter slim" aria-hidden="true"><i style={{ transform: `scaleX(${1 - (first.free ?? 0) / first.total})` }} /></div> : null}
                <span className="sub">{first.total ? `${fmt(first.free)} free of ${fmt(first.total)}` : "Drive not reachable"}</span>
              </>
            ) : <span className="sub">No backup drive set</span>}
            <span className="sub">Last backup: {stats?.last_backup ?? "never"}</span>
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
              {HOSTED && <a className="btn" href={INSTALLER_URL} download title="Install the Windows app so it can back up this PC"><Icon name="download" /><span>Install<span className="hide-sm"> for Windows</span></span></a>}
              {busy && <button onClick={() => api("/api/job/cancel", "POST").catch(e => setMsg("Error: " + (e as Error).message))}><Icon name="cancel" /><span className="hide-sm">Cancel</span></button>}
              <button aria-label="Scan files" onClick={() => start("/api/scan")} disabled={busy}><Icon name="scan" /><span className="hide-sm">Scan files</span></button>
              <button className="primary" onClick={() => start("/api/backup")} disabled={busy || !stats?.files}><Icon name="backup" />Back up<span className="hide-sm"> now{stats?.pending_bytes ? ` (${fmt(stats.pending_bytes)})` : ""}</span></button>
            </div>
          </header>

          <main className="content">
            {!busy && msg && <p className="msg" role="status">{msg}</p>}
            <Page key={["review", "selected", "files", "restore"].includes(tab) ? tab + ":" + tick : tab}>
              {tab === "dashboard" && <Dashboard stats={stats} busy={busy} go={setTab} onJob={onJob} />}
              {tab === "review" && <Review onChange={loadStats} />}
              {tab === "selected" && <Review mode="selected" onChange={loadStats} />}
              {tab === "files" && <Files onChange={loadStats} />}
              {tab === "restore" && <Restore onJob={onJob} />}
              {tab === "devices" && <Devices />}
              {tab === "organize" && <Organize busy={busy} onJob={onJob} />}
              {tab === "logs" && <Logs tick={tick} />}
              {tab === "settings" && <SettingsTab onSaved={loadStats} />}
            </Page>
          </main>
        </div>
      </div>
    </MotionConfig>
  );
}
