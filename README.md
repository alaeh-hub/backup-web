# Ala Eh! File Backup

A local backup tool for Windows PCs (Flask + React + TypeScript). It scans a PC, lets you choose what to
back up, and copies the chosen files to an external drive. Several PCs can share one drive: each PC gets its
own folder. Your files never leave your machines (the fonts are bundled, and the only internet request is the optional update check) and there is no database; settings and the file list are JSON files
in `~/.ala-eh-backup` (change with `BACKUP_DATA_DIR`).

## Install (Windows)

Download `AlaEhBackup-Setup.exe` from the [latest release](https://github.com/alaeh-hub/backup-web/releases/latest)
(or use the **Download for Windows** button on the hosted site, which is only a download page) and run it. No admin rights are needed. Open
**Ala Eh! File Backup** from the Start Menu: it opens in its own desktop window, with no browser and no console.
Closing the window stops the app, and scheduled scans only run while it is open.

- **Updates:** when the app opens it checks the latest GitHub release. If there is a newer version, a banner shows
  **Update now**: the app downloads the installer (only from GitHub, checked against its size and SHA-256), installs
  it silently and reopens by itself. Nothing is installed without that click. Turn the check off in Settings, under
  Updates, or with no internet it is simply skipped. You can also run a newer installer over the old one by hand.
  Settings and history are kept in `~/.ala-eh-backup`. It always goes to the highest released version, even if you
  skipped some. The installer closes any copy still running (including leftover background processes) and reopens the
  app when it finishes. The installed app uses port 5100 (so it never clashes with a dev copy on 5001) and has its own
  Ala Eh logo (`installer/app.ico`) in the window, taskbar and exe.
- The installer is not code-signed, so Windows SmartScreen may warn: choose **More info**, then **Run anyway**.
- The app always runs on the PC it backs up. The Vercel deployment contains only the download page (`vercel.json` has just the
  frontend service, no `/api` route), and the backend also refuses every `/api` call there unless `BACKUP_PASSWORD` is set. A deployed site (for example Vercel) shows only the download page,
  because a server cannot see your files. Addresses on your own network (`192.168.x.x`, `10.x.x.x`, a PC name) get the
  full app, so `BACKUP_HOST` access from a phone or laptop works. On `localhost`/`127.0.0.1` (dev server or the installed app) you get the full app; add `?download` to the address (`http://127.0.0.1:5174/?download`) to preview the download page.

## Run from source (development)

Needs Python 3.12 or newer and Node.js 20 or newer.

    py app.py

On first run this installs the Python and npm packages, starts the backend (http://127.0.0.1:5001) and the
frontend (http://127.0.0.1:5174), and opens the browser. Ctrl+C stops both. `NO_BROWSER=1` skips opening the
browser and `FRONTEND_PORT` changes the frontend port.

In this mode the app opens in your browser. Open the app at `localhost` or `127.0.0.1`. Other host names are refused on purpose.

## How it works

1. **Scan files.** Walks every internal drive (or only the folders you choose in Settings) and records each
   file's name, size and date. System and junk folders (Windows, Program Files, `AppData`, `node_modules`,
   caches, temp files) are skipped. The backup drive is never scanned. External drives that Windows reports as
   removable are not scanned either.
2. **Decide what to back up.** Every new file waits in **New files** until you choose. Use a **Quick pick**
   (Office PC, Documents only, Everything) in **Files**, choose by folder, by type or by size, or decide in
   **New files**. **Selected** lists everything chosen. Skipped files stay skipped.
3. **Back up now.** Scans, then copies only chosen files that are new or changed to the backup drive, into a
   folder named after the PC. A changed file replaces its old copy; no older versions are kept. A copy is
   written beside the old one and swapped in only when complete.
4. **Next time.** Only genuinely new files appear in New files, and only changed files are copied. A scan or
   backup with nothing to do says so.

Other parts:

- **Devices** lists every PC that has a folder on the backup drive. Each PC is recognised by an ID file, so two
  PCs with the same name never share a folder. The drive itself is remembered by its serial number and is found
  again if Windows gives it another letter.
- **Restore** puts files back in their original place or another folder, including files deleted from the PC.
- **Verify** re-checks backed up copies. **Organize** gathers documents, pictures and videos into one sorted folder.
- **Compare file contents** (Settings): normally a file counts as unchanged when its size and date match. Turn this on to also
  hash such files on every backup and catch an edit that kept the same size and date (slower).
- **Scheduled scan** (Settings) scans on chosen days and times so new files are waiting for review. It never
  copies anything by itself.
- **Compression** (Settings): off by default (plain copies). Turn it on and each backup run is saved as one archive per
  drive (`.zip`, `.7z`, `.tar.gz`, `.tar.bz2` or `.tar.xz`) in the `_archives` folder of this PC, with your folders kept
  inside. Only new or changed files go into a run's archive; an older archive is deleted once none of its files are
  still needed. Restore and Verify read single files out of the archives and still handle older per-file copies.
  RAR is not offered because only WinRAR can create RAR files. 7z needs `py7zr` (in `requirements-desktop.txt`,
  bundled in the installer).
- Optional webhook message (Slack, Discord or any JSON endpoint) after scheduled scans and backups.

## Back up another PC over your network

Two PCs that both run this app can work together. **B** is the PC to protect, **A** has the backup drive. The same app
does both jobs; nothing special is installed.

1. **On B:** open **Other PCs**, add the folders to share, click **Turn sharing on**, then **Show a pairing code**.
2. **On A:** open **Other PCs**, click **Find PCs on this network** (or type B's address), enter the 6-digit code and
   **Pair**. Tick the folders of B to back up.
3. **Back up as usual** on A: B's files appear in New files / Files, and **Back up now** copies them to A's drive under
   `<A's folder>/Remote PCs/<B's name (short id)>/<folder>` (the short id keeps two PCs with the same name apart). Verify and Restore work like any other file (restore asks for a folder).

How it stays safe:

- Sharing is **off** until the owner turns it on, **read-only**, and limited to the chosen folders. This app's own data
  (it holds the private key), `.ssh`, `.gnupg`, `.aws` and similar folders are never served, and cannot be chosen as a shared folder either.
- Pairing uses a one-time code that works once, for 5 minutes, with 5 tries (SPAKE2: the code is never sent and cannot
  be guessed offline). Afterwards each PC is recognised by its certificate (mutual TLS); a different certificate is refused
  before anything is sent. B can **Remove** a PC at any time and it loses access at once.
- Only addresses on your own network are served. The app does not use UPnP or open router ports.
- B shows who is connected and a log of every request. Sharing turns itself off after a few hours unless you choose otherwise.
- File names sent by another PC are checked before they become paths on A's drive.

Needs: both PCs on the same Wi-Fi or network, B on and awake, and this app running on A while it backs up. The first time,
Windows asks whether to allow the app: allow **private networks** only. `BACKUP_SHARE_HOST` limits sharing to one address.
Not covered yet: the internet (use a VPN), files other programs keep open, and system folders.

## Security

- The server binds to `127.0.0.1`. Only pages from this PC may call it: other host names and other sites are
  refused. Setting `BACKUP_HOST` to expose it on the network requires `BACKUP_PASSWORD`.
- `BACKUP_PASSWORD` turns on a sign-in (5 wrong tries a minute, then a short lock).
- Network paths (`\\server\share`) are not accepted for drives, restore or browsing.

## Development

    pip install -r backend/requirements.txt -r backend/requirements-dev.txt
    python -m pytest backend/tests

    cd frontend
    npm ci
    npm run dev        # http://localhost:5174, proxies /api to the backend on 5001
    npm run build      # type check and production build into frontend/dist

### Building the installer

    powershell -ExecutionPolicy Bypass -File installer\build.ps1

Needs Node.js, Python 3.12+ and [Inno Setup 6](https://jrsoftware.org/isinfo.php). It builds the frontend,
packs the app with PyInstaller (`backend/desktop.py`, a native window via pywebview; desktop-only packages are
in `backend/requirements-desktop.txt`) and writes `installer/out/AlaEhBackup-Setup.exe`.

### Releasing

Work on a branch and open a pull request; do not push to `main` directly. Bump the version in
`frontend/package.json`, `installer/setup.iss` and `installer/build.ps1`. When the PR is merged,
`.github/workflows/release.yml` reads the version from `frontend/package.json`. If there is no release for it yet,
it builds the installer on Windows, tags `vX.Y.Z` and publishes `AlaEhBackup-Setup.exe` and `AlaEhBackup.exe` as a
GitHub Release. If the version was not bumped, nothing is released. You can also run it by hand from the Actions
tab to get the files as a downloadable artifact. See `AGENTS.md` for the rules AI assistants follow in this repo.

### Continuous integration

Continuous integration (`.github/workflows/ci.yml`) runs the backend tests on Linux and Windows, and the
frontend type check, build and a dependency audit, on every push to `main` and every pull request.

## Not included

Cloud upload, encryption, accounts, and a central view of many PCs beyond the Devices list.
