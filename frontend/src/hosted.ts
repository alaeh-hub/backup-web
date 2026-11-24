/** Where the Windows installer is published (GitHub Releases: attach AlaEhBackup-Setup.exe to the latest release). */
export const INSTALLER_URL = "https://github.com/alaeh-hub/backup-web/releases/latest/download/AlaEhBackup-Setup.exe";
export const RELEASES_API = "https://api.github.com/repos/alaeh-hub/backup-web/releases/latest";

/** True for this PC and for addresses on the same network (a phone or laptop using BACKUP_HOST), where the app itself is served. */
export function isLocalHost(hostname: string): boolean {
  const h = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (h === "localhost" || h === "::1" || h.endsWith(".localhost") || h.endsWith(".local")) return true;
  if (!h.includes(".") && !h.includes(":")) return true;                       // a bare PC name on the LAN
  const m = h.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (m) {
    const a = Number(m[1]), b = Number(m[2]);
    return a === 127 || a === 10 || (a === 192 && b === 168) || (a === 172 && b >= 16 && b <= 31) || (a === 169 && b === 254);
  }
  return h.startsWith("fe80:") || h.startsWith("fc") || h.startsWith("fd");   // IPv6 link-local and unique-local
}

/** True on a deployed site (Vercel). The app only runs on the PC it backs up or on its own network. */
export const HOSTED = !isLocalHost(location.hostname);
/** Preview the download page locally: open http://127.0.0.1:5174/?download */
export const SHOW_DOWNLOAD = HOSTED || new URLSearchParams(location.search).has("download");
