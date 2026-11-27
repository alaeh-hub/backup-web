import { useCallback, useEffect, useState } from "react";
import { api, fmt, DeviceDrive } from "./api";
import { Icon } from "./ui";
import { Cluster, Group } from "./Panel";
import { SearchBox } from "./SearchBox";
import { smartFilter } from "./smart";

interface Size { bytes: number; files: number; complete: boolean }

export function Devices() {
  const [drives, setDrives] = useState<DeviceDrive[] | null>(null); const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [sizes, setSizes] = useState<Record<string, Size | "busy">>({});
  const load = useCallback(async () => { try { setErr(""); setDrives(await api<DeviceDrive[]>("/api/devices")); } catch (e) { setErr((e as Error).message); } }, []);
  useEffect(() => { load(); }, [load]);
  const measure = async (dest: string, folder: string) => {
    const k = dest + "\u0000" + folder;
    setSizes(s => ({ ...s, [k]: "busy" }));
    try { const r = await api<Size>(`/api/devices/size?dest=${encodeURIComponent(dest)}&folder=${encodeURIComponent(folder)}`); setSizes(s => ({ ...s, [k]: r })); }
    catch (e) { setErr((e as Error).message); setSizes(s => { const n = { ...s }; delete n[k]; return n; }); }
  };
  if (err) return <p className="err">Could not load the devices: {err}</p>;
  if (!drives) return <p className="sub">Loading...</p>;
  if (!drives.length) return (
    <Group title="Devices" lead="Every PC that has a folder on your backup drives.">
      <div className="blank"><b>No backup drive yet.</b><span className="sub">Add a backup drive in Settings. Every PC that backs up to it will appear here.</span></div>
    </Group>
  );
  return (
    <Group title="Devices" lead="Every PC that has a folder on your backup drives, and when it last backed up.">
      <div className="toolbar"><SearchBox label="Search devices" placeholder="Search by PC name, user or drive" value={q} onChange={setQ} /></div>
      {drives.map(d => { const devs = smartFilter(d.devices, q, v => `${v.name} ${v.user ?? ""} ${v.folder} ${d.dest} ${d.label ?? ""}`); return (
        <Cluster key={d.dest} title={`${d.dest}${d.label ? ` (${d.label})` : ""}`}>
          {!d.reachable && <p className="warn">This drive is not connected. Plug it in and reload.</p>}
          {d.reachable && !devs.length && !!q.trim() && !!d.devices.length && <p className="sub">No PC on this drive matches “{q}”.</p>}
          {d.reachable && !d.devices.length && <div className="blank"><b>No PC has backed up to this drive yet.</b></div>}
          <ul className="rows">
            {devs.map(v => {
              const sz = sizes[d.dest + "\u0000" + v.folder];
              return (
                <li key={v.folder} className="line">
                  <Icon name="drive" />
                  <span className="grow"><b>{v.name}</b>{v.this_pc && <span className="tag new"> This PC</span>}<br />
                    <span className="sub">{v.user ? `User ${v.user}. ` : ""}Last backup {v.last_backup ?? "not recorded"}. First backup {v.first_backup ? v.first_backup.replace("T", " ") : "not recorded"}.{v.backed_up_by?.length ? ` Also backed up over the network from ${v.backed_up_by.join(", ")}.` : ""}</span></span>
                  {sz && sz !== "busy" ? <strong>{fmt(sz.bytes)}{sz.complete ? "" : " or more"} <span className="sub">{sz.files.toLocaleString()} files</span></strong>
                    : <button disabled={sz === "busy"} onClick={() => measure(d.dest, v.folder)}>{sz === "busy" ? "Measuring..." : "Show size"}</button>}
                </li>
              );
            })}
          </ul>
        </Cluster>
      ); })}
    </Group>
  );
}
