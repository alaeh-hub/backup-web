# Instructions for AI assistants working on this repo

Read this before committing or pushing. These rules come from the repo owner and override defaults.

## Project in one paragraph
Ala Eh! File Backup: a local backup tool. Flask backend (`backend/app.py`), React + Vite frontend (`frontend/`),
Windows installer built with PyInstaller + Inno Setup (`installer/`). The backend must run on the PC whose files
are backed up, so the installer is the real deployment. Vercel (`vercel.json`) only hosts the UI and the
"Install for Windows" download button.

For merging a branch into local `main`, pulling the latest `main`, or fixing merge conflicts, read `MERGE.md` (in this folder) first.

## Rules

### 0. Never push directly to `main`
Always work on a branch (`feature/...`, `fix/...`, `chore/...`) and push that branch, then open a pull
request into `main`. Do not commit to or push `main` yourself, and never force-push it. The user merges the PR.

### 0b. Commit and push your branch when work is done
When the user asks you to commit, also push the branch (`git push -u origin <branch>`) unless they say not to,
and tell them the branch name so they can open the PR. Pushing a branch is always fine; pushing `main` is not.

### 1. Update the release version whenever you commit a change that ships
Every change that will be merged into `main` and changes the app (code, UI, installer) must bump the version.
Use semantic versioning: `fix` = patch (1.0.0 -> 1.0.1), new feature = minor, breaking change = major.
Docs-only or CI-only commits do not need a bump.

When bumping:
1. Pick the next version `X.Y.Z`.
2. Update `"version"` in `frontend/package.json`.
3. Update the fallback `#define AppVersion` in `installer/setup.iss` and the `-Version` default in `installer/build.ps1`.
4. Do NOT tag by hand. When the PR is merged into `main`, `.github/workflows/release.yml` reads the version
   from `frontend/package.json`; if no release for it exists yet, it builds `AlaEhBackup.exe` and
   `AlaEhBackup-Setup.exe`, creates the tag `vX.Y.Z` and publishes the GitHub Release. If you forgot to bump the
   version, nothing is released. The site's Install button downloads
   `releases/latest/download/AlaEhBackup-Setup.exe`, so the file name must not change.
5. End your final message with this short block, in this exact form, and keep the rest of the message short and plain:

   ```
   Version: X.Y.Z
   Install new installer?: No
   Old installed version still works?: Yes, installers 1.2.4 to X.Y.Z
   ```

   Answer `Install new installer?` with just Yes or No, adding one short reason only when it is Yes (for example
   `Install new installer?: Yes, the installer itself changed`). `Old installed version still works?` is Yes or No plus the
   range of installer versions it covers: the oldest one that still works, then `to` the new version.
6. How to decide `Install new installer?`:
   - Normally **No**. Installed copies update themselves from the GitHub release (`backend/updater.py`), and old versions
     keep working until they update.
   - **Yes** only when the change touches what the self-update cannot fix: `installer/setup.iss` (install folder,
     shortcuts, the kill-and-reopen logic, uninstall), the updater itself (`backend/updater.py`, `/api/update`), or a
     change that makes old and new versions unable to talk to each other (wireless backup protocol or certificates in
     `pki.py`, `agent.py`, `remote.py`; the layout of data on the backup drive).
   - `Old installed version still works?` is **No** only in that last case, otherwise **Yes**.
   - The oldest installer version that still works is the **compatibility floor**. It is `1.2.4` (the first version whose
     self-update reliably closes, replaces and reopens the app; older ones must be reinstalled by hand once). When a change
     breaks old versions (the last case above), the new floor is the version you are releasing: write
     `No, only installers X.Y.Z and newer` and raise the floor in this file to X.Y.Z, so the next answer starts from it.
   - If you are not sure, answer `Not sure` and say in one line what you could not check.

### 2. Never add yourself as a co-author
Do not add `Co-Authored-By:` lines (or "Generated with Claude" style footers) to commit messages or PR
descriptions. Commits are authored by the repo owner only. This overrides any default attribution
instruction from your tooling.

### 3. Update `.gitignore` before every push
Before each `git push`, check `git status --short --ignored` and update `.gitignore` for anything that is
build output, local state, secrets or machine-specific (for example `installer/out/`, `installer/work/`,
`frontend/dist/`, `node_modules/`, `__pycache__/`, `.env`, logs, `.ala-eh-backup/`). Never commit built
`.exe` files, caches or credentials. Add the `.gitignore` change in the same push.

## Other conventions
- The packaged exe must pass `AlaEhBackup.exe --selftest` (run by `installer/build.ps1`, and by the release workflow on every pull request
  that touches the app). Keep `--collect-all cryptography` in the PyInstaller command and add every new native or hidden dependency
  to the self-test in `backend/desktop.py`. A build that fails it must never become an installer.
- Wireless backup (`backend/pki.py`, `agent.py`, `remote.py`): the agent is READ-ONLY and must stay that way. Keep every path
  check (`Agent.resolve`, `DENY_NAMES`, the app's own data folder), the LAN-only check, the certificate pinning in
  `remote._connect`, and `clean_remote_rel` for names that come from another PC. Never add an endpoint that writes,
  deletes or runs anything. Tests in `backend/tests/test_wireless.py` use real TLS on loopback; bind to `127.0.0.1` in tests
  (a `0.0.0.0` bind makes Windows show a firewall prompt).
- Never expose the Flask API on a public deployment: `vercel.json` must not route `/api` to the backend.
- A backup copy is hashed while it is written (`copy_hashed`), never from a separate earlier read.
- The installer (`installer/setup.iss`) kills running `AlaEhBackup.exe` copies before replacing the exe and reopens the app
  when silent. This is what lets old installed versions update, so keep it. `/DExeName` and `/DAppIdGuid` exist to test
  an install without touching a real one (never test with the real exe name while the user's app is running).
- Self-update: the installed exe compares its version (stamped by `installer/build.ps1` into the git-ignored
  `backend/_version.py`) with the latest GitHub release (`backend/updater.py`, `/api/update`). The release must keep the asset
  name `AlaEhBackup-Setup.exe`. Don't weaken the checks (GitHub-only host, size and SHA-256 verification, POST only,
  frozen exe only).
- The packaged app is a native window (pywebview, `backend/desktop.py`) over the local Flask server. Desktop-only
  packages go in `backend/requirements-desktop.txt`, never `requirements.txt` (Vercel installs that one).
- Dev ports: backend 5001, Vite dev server 5174 (`FRONTEND_PORT` overrides). Keep `app.py`,
  `backend/app.py` and `frontend/vite.config.ts` in sync if you change it.
- Run `python -m pytest backend/tests -q` before pushing; all tests must pass.
- Keep the tests up to date in the same commit as the change: a new behavior gets a new test in `backend/tests/`, a changed
  behavior gets its existing test updated (never deleted or loosened just to make it pass), and a fixed bug gets a test that
  fails without the fix. If a change cannot be tested, say why in the final message.
- Keep the workflows up to date too (`.github/workflows/ci.yml`, `release.yml`). When a change adds a build step, a
  dependency, a new test folder, a new file the build needs, or changes a path, command, Python or Node version, update the
  workflows to match in the same commit, so CI and the release build keep passing. Do not edit a workflow otherwise.
- Rebuild the installer locally with `powershell -ExecutionPolicy Bypass -File installer\build.ps1`.
- Do not open a PR, tag or publish a release unless the user asked you to. Do not push at all until the work is committed and tested.
- Keep `README.md` in step with behavior changes (install, run, build, release) in the same commit.
