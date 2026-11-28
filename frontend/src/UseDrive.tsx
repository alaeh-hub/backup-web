import { useState } from "react";
import { api } from "./api";
import { ask, tell } from "./Dialog";

/**
 * A different drive is on a backup location than the one used before (a new disk, or a reformatted one). This asks once,
 * then makes it the backup drive: everything is copied to it again from the start.
 */
export function UseDrive({ path, name, onDone, compact }: { path: string; name?: string; onDone: () => void; compact?: boolean }) {
  const [busy, setBusy] = useState(false);
  const go = async () => {
    const label = name ? `${path} (${name})` : path;
    if (!await ask(`Use the drive on ${label} as your backup drive from now on?\n\nThe old drive is not connected, so its copies are not there. Everything is copied to this drive again, and files already on it are kept, not written twice.`, "Use this drive")) return;
    setBusy(true);
    try { await api("/api/destinations/use-new", "POST", { path }); onDone(); }
    catch (e) { await tell("Could not switch drives: " + (e as Error).message); }
    setBusy(false);
  };
  return (
    <div className={"use-drive" + (compact ? " compact" : "")} role="group" aria-label={`A different drive is on ${path}`}>
      <p className="warn">{path} is now a different drive{name ? `, ${name}` : ""}, not the one used before. Backups are paused so nothing goes to the wrong disk.</p>
      <button className="primary" onClick={go} disabled={busy}>{busy ? "Switching..." : "Use this drive"}</button>
    </div>
  );
}
