# Revision history

This repository was reworked in October 2026 (project renamed from `os-dnscrypt-eu` to `os-dnscrypt-routes`). The plan is
[`clear-cut-revision-plan.html`](clear-cut-revision-plan.html); it still describes the requirements (`R-xx`) and contracts (`C-xx`).

## Where the old material lives (git tags)

| Tag | What it holds |
|---|---|
| `pre-revision` | The repository as it was before the rework: the old plugin, tests, process documents and the four old guides. Read a file with `git show pre-revision:<path>`, e.g. `git show pre-revision:docs/plugin-build-and-install.md`. |
| `revision-process` | The last commit that still contains the process documents of the rework: `docs/implementation/` (roles, 34 work-packet files with their review logs, milestone reviews, the kickoff prompt) and `.claude/agents/`. Read them with `git show revision-process:docs/implementation/work-packets.md` or `git checkout revision-process`. |

## How it was done

Work packets WP-01 to WP-13 plus 21 fix packets were implemented by separate agents in separate worktrees, each reviewed by a
fresh independent reviewer until nothing of minor severity or higher was open, and each milestone (M1 to M5) was reviewed from
two lenses (correctness and contracts; the user's and operator's view). The test VM (`test-vm/`) was used for every on-device
check. The owner approved the release candidate (M5) after the third review round.

## What was decided on the way (so you do not have to rediscover it)

- The VM tooling stays small on purpose. At the end the owner removed two optional VM checks (the protocol-drift fixture and the
  scripted UI check) to keep it lean; the relay-only backstop for those is covered by the offline tests.
- `vm test` always starts from the stock 26.7 baseline. To test an updated guest, use the reset-free subset in `test-vm/README.md`.
- The committed snapshot `test-vm/snapshots/2026-10-15/` and the historical bundle `test-vm/restore/2026-10-11/` are throw-away
  VM configurations; the bundle stays byte-identical to its state in `pre-revision`.
