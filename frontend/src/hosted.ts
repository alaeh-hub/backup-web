/** Where the Windows installer is published (GitHub Releases: attach AlaEhBackup-Setup.exe to the latest release). */
export const INSTALLER_URL = "https://github.com/alaeh-hub/backup-web/releases/latest/download/AlaEhBackup-Setup.exe";
export const RELEASES_API = "https://api.github.com/repos/alaeh-hub/backup-web/releases/latest";
/** True on a deployed site. The app itself only runs on the PC it backs up (dev server or installed app), always on localhost. */
export const HOSTED = !["localhost", "127.0.0.1", "::1", "[::1]"].includes(location.hostname);
/** Preview the download page locally: open http://127.0.0.1:5174/?download */
export const SHOW_DOWNLOAD = HOSTED || new URLSearchParams(location.search).has("download");
