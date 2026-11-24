# Ala Eh! File Backup

A local backup tool for Windows PCs (Flask + React + TypeScript). It scans a PC, lets you choose what to
back up, and copies the chosen files to an external drive. Several PCs can share one drive: each PC gets its
own folder. Nothing leaves the machine and there is no database; settings and the file list are JSON files
in `~/.ala-eh-backup` (change with `BACKUP_DATA_DIR`).

## Install (Windows)

Download `AlaEhBackup-Setup.exe` from the [latest release](https://github.com/alaeh-hub/backup-web/releases/latest)
(or use the **Install for Windows** button on the hosted site) and run it. No admin rights are needed. Open
**Ala Eh! File Backup** from the Start Menu: it opens in its own desktop window, with no browser and no console.
Closing the window stops the app, and scheduled scans only run while it is open.

- To update, run the newer installer over the old one. Settings and history are kept in `~/.ala-eh-backup`.
- The installer is not code-signed, so Windows SmartScreen may warn: choose **More info**, then **Run anyway**.
- The app always runs on the PC it backs up. The Vercel site only hosts the page and the download button; the
  backend there cannot see your files.

## Run from source (development)

Needs Python 3.12 or newer and Node.js 20 or newer.

    py app.py

On first run this installs the Python and npm packages, starts the backend (http://127.0.0.1:5000) and the
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
- **Scheduled scan** (Settings) scans on chosen days and times so new files are waiting for review. It never
  copies anything by itself.
- **Compression** (Settings): off by default (plain copies). Turn it on and each backup run is saved as one archive per
  drive (`.zip`, `.7z`, `.tar.gz`, `.tar.bz2` or `.tar.xz`) in the `_archives` folder of this PC, with your folders kept
  inside. Only new or changed files go into a run's archive; an older archive is deleted once none of its files are
  still needed. Restore and Verify read single files out of the archives and still handle older per-file copies.
  RAR is not offered because only WinRAR can create RAR files. 7z needs `py7zr` (in `requirements-desktop.txt`,
  bundled in the installer).
- Optional webhook message (Slack, Discord or any JSON endpoint) after scheduled scans and backups.

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
    npm run dev        # http://localhost:5174, proxies /api to the backend on 5000
    npm run build      # type check and production build into frontend/dist

### Building the installer

    powershell -ExecutionPolicy Bypass -File installeruild.ps1

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
