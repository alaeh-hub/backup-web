# Instructions for AI assistants working on this repo

Read this before committing or pushing. These rules come from the repo owner and override defaults.

## Project in one paragraph
Ala Eh! File Backup: a local backup tool. Flask backend (`backend/app.py`), React + Vite frontend (`frontend/`),
Windows installer built with PyInstaller + Inno Setup (`installer/`). The backend must run on the PC whose files
are backed up, so the installer is the real deployment. Vercel (`vercel.json`) only hosts the UI and the
"Install for Windows" download button.

## Rules

### 0. Never push directly to `main`
Always work on a branch (`feature/...`, `fix/...`, `chore/...`) and push that branch, then open a pull
request into `main`. Do not commit to or push `main` yourself, and never force-push it. The user merges the PR.

### 1. Update the release version whenever you commit a change that ships
Every change that will be merged into `main` and changes the app (code, UI, installer) must bump the version.
Use semantic versioning: `fix` = patch (1.0.0 -> 1.0.1), new feature = minor, breaking change = major.
Docs-only or CI-only commits do not need a bump.

When bumping:
1. Pick the next version `X.Y.Z`.
2. Update `"version"` in `frontend/package.json`.
3. Update the fallback `#define AppVersion` in `installer/setup.iss` and the `-Version` default in `installer/build.ps1`.
4. Only after the PR is merged into `main` (and only if the user asks you to release), switch to the
   updated `main` and create and push the tag:
   `git tag vX.Y.Z && git push origin vX.Y.Z`
   The tag triggers `.github/workflows/release.yml`, which builds `AlaEhBackup.exe` and
   `AlaEhBackup-Setup.exe` and publishes them as a GitHub Release. The site's Install button downloads
   `releases/latest/download/AlaEhBackup-Setup.exe`, so the file name must not change.
5. Mention the new version in your final message to the user.

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
- The packaged app is a native window (pywebview, `backend/desktop.py`) over the local Flask server. Desktop-only
  packages go in `backend/requirements-desktop.txt`, never `requirements.txt` (Vercel installs that one).
- Dev ports: backend 5000, Vite dev server 5174 (`FRONTEND_PORT` overrides). Keep `app.py`,
  `backend/app.py` and `frontend/vite.config.ts` in sync if you change it.
- Run `python -m pytest backend/tests -q` before pushing; all tests must pass.
- Rebuild the installer locally with `powershell -ExecutionPolicy Bypass -File installer\build.ps1`.
- Do not push, open a PR, tag or publish a release unless the user asked you to.
