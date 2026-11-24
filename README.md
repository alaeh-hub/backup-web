# Ala Eh! File Backup

A local backup tool for Windows PCs (Flask + React + TypeScript). It scans a PC, lets you choose what to
back up, and copies the chosen files to an external drive. Several PCs can share one drive: each PC gets its
own folder. Nothing leaves the machine and there is no database; settings and the file list are JSON files
in `~/.ala-eh-backup` (change with `BACKUP_DATA_DIR`).

## Run

Needs Python 3.12 or newer and Node.js 20 or newer.

    py app.py

On first run this installs the Python and npm packages, starts the backend (http://127.0.0.1:5001) and the
frontend (http://127.0.0.1:5174), and opens the browser. Ctrl+C stops both. `NO_BROWSER=1` skips opening the
browser and `FRONTEND_PORT` changes the frontend port.

Open the app at `localhost` or `127.0.0.1`. Other host names are refused on purpose.

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
    npm run dev        # http://localhost:5174, proxies /api to the backend on 5001
    npm run build      # type check and production build into frontend/dist

Continuous integration (`.github/workflows/ci.yml`) runs the backend tests on Linux and Windows, and the
frontend type check, build and a dependency audit, on every push to `main` and every pull request.

## Not included

Cloud upload, encryption, accounts, and a central view of many PCs beyond the Devices list.
