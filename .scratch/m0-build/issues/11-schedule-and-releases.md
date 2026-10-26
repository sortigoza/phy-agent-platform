# Schedule and Releases

Type: AFK
Status: done
Blocked by: 10

## Goal

`phy schedule install` runs `phy daily` from a Release (a tagged version) checked out at `$PHY_HOME/app`, never from the dev clone, and the Reader is told when a newer Release exists and installs it with `phy schedule update`.

## Sources

SPEC §5 Scheduling and Releases; QUICK_START §5; GLOSSARY Release; the Q6 and Q9–Q12 answers on [Slice M0 into implementation tickets](../../m0/issues/08-slice-m0.md).

## Acceptance criteria

- A Release is an annotated tag `vMAJOR.MINOR.PATCH` on `main`; the newest is `git tag --list 'v*' --sort=-v:refname` ignoring pre-release tags. phy never creates tags.
- `phy schedule install` refuses when no Release exists; otherwise `git worktree add --detach $PHY_HOME/app <newest tag>`, `uv sync` there, and writes and loads `~/Library/LaunchAgents/phy.daily.plist`: `StartCalendarInterval` 06:00, `RunAtLoad`, the absolute `uv` path, `WorkingDirectory` `$PHY_HOME/app`, `PHY_HOME` in `EnvironmentVariables` (never a secret), `StandardErrorPath` `$PHY_HOME/logs/launchd.err`. Idempotent. `$PHY_HOME/.gitignore` ignores `app/`.
- `phy schedule status`: loaded or not, the installed Release, last run time and exit status.
- `release_status()` (replacing the stub from 06): installed tag (`git -C $PHY_HOME/app describe --tags`), newest tag, commits between them and their subjects; purely local, no fetch.
- `phy schedule update` takes `phy.lock`; does nothing when already on the newest Release; refuses a downgrade; otherwise `git -C $PHY_HOME/app checkout --detach <tag>`, `uv sync`, prints the commit subjects. Migrations apply on the next connect.
- The `/` top-bar badge, `phy status` and one INFO `schedule.update_available` line from `phy daily` show a pending Release; no tile, no red.
- `phy schedule uninstall` unloads and removes the plist and the worktree.

## Tests first

- Plist XML from a fixed config matches a golden file (plistlib), including the absolute `uv` path.
- In a temporary git repo with tags `v0.1.0`, `v0.2.0`, `v0.3.0-rc1`: newest is `v0.2.0`; install checks out `v0.1.0` when that's the only tag; update moves to `v0.2.0` and lists subjects; update again is a no-op; a lower tag is refused; no tags → install refuses.
- `launchctl` calls go through one function that tests replace.

## Lift from

Nothing.

## Not in this slice

macOS notifications (M1). Starting the burn-in (17).
