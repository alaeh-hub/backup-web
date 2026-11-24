/** Where the Windows installer is published (GitHub Releases: attach AlaEhBackup-Setup.exe to the latest release). */
export const INSTALLER_URL = "https://github.com/alaeh-hub/backup-web/releases/latest/download/AlaEhBackup-Setup.exe";
export const RELEASES_API = "https://api.github.com/repos/alaeh-hub/backup-web/releases/latest";
/** True on a deployed site. The app itself only runs on the PC it backs up (dev server or installed app), always on localhost. */
export const HOSTED = !["localhost", "127.0.0.1", "::1", "[::1]"].includes(location.hostname);
