# Merge guide for AI assistants

Read this when the user wants to merge their branch into local `main`, bring a branch up to date, or fix merge conflicts.
It works together with `AGENTS.md` (those rules still apply).

## The one rule: main wins, the direction is branch -> main
- `main` is the source of truth. The branch is what gets adjusted to fit it.
- The merge always goes **branch into main**. Never merge `main` into the branch as the way to finish the work, and never
  overwrite `main` with the branch's old copy of a file.
- When a conflict is not clear, keep what `main` already has and re-apply only the branch's new change on top of it.
- Never drop something that is already in `main` (a fix, a version bump, a feature someone else merged) just because the
  branch does not have it.
- Never force-push `main`, never push `main` directly (see `AGENTS.md` rule 0). Merge locally, then the user pushes or opens the PR.

## Step 0: Ask first
Do not merge, pull, rebase, stash or resolve anything until the user says yes.
Ask in plain words, for example: "You are on `feature/x`. Do you want me to merge it into local `main`?"
A "yes" covers this one merge only. Ask again next time.

## Step 1: Look before touching anything
Run these (read-only) and tell the user what you found:
1. `git status --short` and `git branch --show-current`: what branch, and is the working tree clean?
2. `git fetch origin`: only downloads info, changes no files.
3. Is `main` behind the remote (someone merged another branch)?
   - `git rev-list --left-right --count main...origin/main` -> the second number is how many new commits are on the remote.
   - `git log --oneline main..origin/main` shows what came in.
4. Is the branch behind `main`? `git log --oneline <branch>..main` shows commits the branch does not have yet.
5. Will it conflict? `git merge-tree --write-tree main <branch>` (or a dry run `git merge --no-commit --no-ff` then abort).

Report it in this short block, in this exact form (Yes or No, add a number or a name only where shown):

```
Working branch: feature/x
New main to pull?: Yes, 2 new commits (from fix/foo)
Branch behind main?: No
Uncommitted changes?: No
Conflicts expected?: Yes, backend/app.py
```

`New main to pull?` is `No` when `main` already matches `origin/main`. If a line cannot be checked (for example no
internet for `git fetch`), write `Not sure` and say why in one line. Keep everything else in the message short and plain.

If there are uncommitted changes, stop and ask the user: commit them, stash them, or leave them. Never discard them.

## Step 2: Bring local main up to date (pull latest)
Only after the user agreed:
1. `git switch main`
2. `git pull --ff-only origin main`
   - If it cannot fast-forward, stop and tell the user. Do not create a merge commit on `main` or reset it on your own.
3. Tell the user which new commits arrived.

## Step 3: Merge the branch into main
1. Stay on `main`: `git merge --no-ff <branch>` (keep a clear merge commit).
2. No conflicts: run the tests (below), then report.
3. Conflicts: go to the next step.

## Step 4: Fix conflicts (main is the base)
For each file in `git status` marked `both modified`:
1. Open the file and read both sides. The `HEAD` side is `main`; the other side is the branch.
2. Keep everything `main` has. Add the branch's new work on top. If both changed the same lines, combine them so both
   intentions still work. If they truly cannot both stay, keep `main`'s version and tell the user what the branch loses.
3. Remove every `<<<<<<<`, `=======`, `>>>>>>>` marker. Search the file to be sure.
4. Special files:
   - Version (`frontend/package.json`, `installer/setup.iss`, `installer/build.ps1`): the result must be the **higher**
     version, and if both sides bumped, bump once more past `main`'s so the release workflow publishes a new version.
     All three places must show the same number.
   - `README.md`, `AGENTS.md`: keep both sides' new lines, no duplicates.
   - Lock files (`package-lock.json`): do not hand-edit; take `main`'s and re-run the install.
5. `git add <file>` once it is resolved. Do not use `git checkout --theirs/--ours` on a whole file without telling the user why.

## Step 5: Verify, then finish
1. `python -m pytest backend/tests -q` must pass. If the frontend changed, also run its build/type-check in `frontend/`.
2. `git diff main~1 --stat` (or `git show --stat HEAD`) to confirm only the expected files changed.
3. `git commit` to finish the merge if git is waiting for it. Use a normal message. No `Co-Authored-By` line (`AGENTS.md` rule 2).
4. Check `.gitignore` as in `AGENTS.md` rule 3.
5. Do not push `main` and do not open a PR unless the user asks. End with this short block:

   ```
   Merged into main?: Yes
   New main pulled?: Yes, 2 commits
   Conflicts?: Yes, backend/app.py (kept main, re-applied the branch change)
   Tests?: Passed
   Version: X.Y.Z
   ```

   Add one plain sentence only if something needs the user's attention (a conflict where the branch lost something).

## If something goes wrong
- Mid-merge and unsure: `git merge --abort` returns to the state before the merge. Tell the user.
- Never use `git reset --hard`, `git checkout .`, `git clean -fd` or `git push --force` unless the user explicitly asks
  for it after you explained what it destroys.
- If you are not sure which side is right, ask the user instead of guessing.
