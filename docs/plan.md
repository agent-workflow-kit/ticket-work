# ticket-work: implementation plan

This plan implements [`interface.md`](interface.md) (normative) and [`design.md`](design.md) (decisions, live verification, modules). Each issue is expanded into bite-sized test-first steps when it is picked up; this document fixes the stages, the conventions and the version roadmap only.

## Conventions for every stage

- **Gateway boundary.** Every subprocess call (ticketctl, ticket-queue, forgectl, agent-spawn, jobsctl, wtctl, hooks) goes through `src/ticket_work/gateway.py`. Nothing else spawns a process or opens a socket.
- **Fakes and pinned sibling schemas.** Fake binaries for every sibling live in `tests/fakebin/` (copied per repository, never shared). Their JSON outputs are validated against the sibling schemas copied into `tests/` and pinned to a version. A fake can inject any exit code, any error envelope, a timeout and a crash between two calls.
- **Process tests and live tests.** Process tests run the real CLI against the fakes and a temporary state directory, and include crash injection after every step of the start order, the job command and `sync` (the crash-window tables in the interface are the test list). `live` tests use real hosts or a real `claude`, are deselected by default and never run in CI.
- **Golden files.** Every `--json` output, every hook payload, every audit and log record, the prompt file, the branch names and the pending summaries have golden files validated against `schemas/`.
- **Spike regressions.** Every relied-on behavior from the live verification (design.md) is a test: the key-matching table, an empty `prs` for a missing repository is not "absent", `merged_head_sha` is passed to teardown, a missing skill marker, `report.implicit: true` and a wrong skill name fail the start, an unknown kind warning is fatal.
- **Property tests.** The key matcher, the slug derivation, the fencing function (`</untrusted` neutralization), the event catch-up ordering and the `landed` rule.
- **`make verify`** (ruff, pyright, pytest, markdown lint) passes before every commit.
- Untrusted text travels only in files or on stdin; every PR title and body goes through `guard text`.

## Module map

| Module | Stage | Responsibility |
|---|---|---|
| `gateway.py`, `config.py`, `store.py`, `leases.py`, `audit.py`, `sanitize.py` | 0 | process boundary, configuration, state, leases, audit and log records, one output sanitizer |
| `boards.py`, `preconditions.py`, `statusmap.py`, `events.py`, `scope.py`, `exits.py`, `prompt.py`, `artifact.py`, `plugin/` | 1 | pure rules and tables, the bundled plugin |
| `hooks.py`, `outbox.py`, `attention.py`, `cli.py` (read side) | 2 | hook execution, at-least-once delivery, attention set, `list`, `show`, `export`, `prune`, `validate` |
| `claims.py`, `start.py`, `pending.py`, `restore.py` | 3 | the start order, confirmations, claims, restore |
| `job.py`, `adopt.py` | 4 | the job command, agent adoption, `resume`, `stop` |
| `sync.py`, `linking.py`, `teardown.py` | 5 | the sync order, PR linking, events to rules, cleanup, `link`, `unlink` |
| cron, README, live suite | 6 | `cron install`, documentation, `live` tests, macOS checklist |

## Stage 0: Foundations

**Goal**: A package that loads and validates configuration, stores state, takes leases, writes audit and log records and runs every external call through one gateway.
**Success Criteria**: `ticket-work --version`, `validate` (config only) and the global flags work; `state.db` migrates additively; a lease is taken and taken over only when its holder is dead; every call to a fake goes through the gateway.
**Tests**: config precedence and drop-ins against `schemas/config.json`; environment overrides limited to the closed list; migration up and `schema_newer`; lease takeover with PID reuse; audit and log golden files; sanitizer fuzz.
**Status**: Not Started

## Stage 1: Rules and tables (no I/O)

**Goal**: Every decision the interface expresses as a rule or table exists as tested pure code, and the bundled plugin exists.
**Success Criteria**: repository rules and the key-free slug; the key matcher; the closed precondition set with unknown-value handling; status-map rule loading with load-time errors; event derivation with once-per-item keys and ordered catch-up; the phase scope table; the lower-exits mapping table; the fenced prompt builder (trusted facts outside, untrusted inside, nonce, `</untrusted` neutralization, unattended rules); the artifact validator; the plugin with its marker reference file, four sandbox placeholders and bundled profile.
**Tests**: table-driven tests for every row of the interface tables; property tests (matcher, slug, fence); hostile-title and hostile-comment corpora; golden prompt files; artifact validation negatives (wrong marker, wrong token, `implicit`, wrong ticket).
**Status**: Not Started

## Stage 2: Read side, hooks and attention

**Goal**: Everything that reads the store or runs hooks, so later stages only add writers.
**Success Criteria**: `list`, `show`, `export`, `prune` (including `--item KEY`) and `validate` (tools, sites, boards); hook execution with veto and escalation semantics and the outbox with `event_id` and bounded retries; the attention set with its set and clear rules.
**Tests**: hook ordering, process-group signaling on timeout, veto versus escalation exits, outbox redelivery after a crash, `list` retention of items with attention, golden outputs.
**Status**: Not Started

## Stage 3: Start, confirmation and restore

**Goal**: A ticket can be claimed, checked, confirmed (or recorded as pending) and handed to a job, and a failed start is undone.
**Success Criteria**: the start order including the write-ahead `applying` record, the apply outcomes and the confirmation matrix; claim release rules; pending records with `confirm` and `reject`; the `--auto` scan loop (`start.scan_limit`, `scan_exhausted`, the refused-key list so each claim is a distinct ticket); restore by live values; the foreground path without jobsctl; `jobsctl add --dry-run` pre-checks.
**Tests**: crash injection after every step of the start order and the repair of `applying`; `stale_ticket` re-plan; `precondition_failed` and `unmapped` releases with and without `--failed`; ticketctl partial failures; the unattended rules; pending expiry and confirm races; spike regressions.
**Status**: Not Started

## Stage 4: Job command, adoption, resume and stop

**Goal**: The job launches or resumes the agent, survives crashes and reports the outcome faithfully.
**Success Criteria**: the job command (launch, resume, wait; the stored settings snapshot; the outcome to exit mapping; the artifact check; `pre-launch`); agent adoption with its three results; `resume`; `stop` with its immediate effect, restart and dismissal paths; held jobs and their pending `launch` records.
**Tests**: process tests per agent outcome (done, blocked, needs-input, failed, unreported, killed, timeout, lost, launch failure); cancel and force-cancel; adoption spoofing; restart of `failed` and `stopped` items; `live` refusal.
**Status**: Not Started

## Stage 5: Sync, linking and cleanup

**Goal**: The guaranteed path from a pull request to a ticket transition and a torn-down worktree.
**Success Criteria**: the sync order (claims, jobs, agents, discovery and read, stale flags, rules, cleanup, attention); PR linking by tier with verification; `link` and `unlink`; events to rules to pending or applied; the `landed` rule; teardown with the merged head; ticket comments (opt-in); `ticket_diverged` and idle flags; lapsed-claim re-take; `sync KEY` and `--dry-run` store no cursor.
**Tests**: the full event scenario table (opened, ready, merged, closed, stacked, forked, scratch base, several pull requests); discovery with `complete: false`, a missing repository, a renamed repository; teardown refusals and retries; crash injection per sync step; concurrent `sync` and job.
**Status**: Not Started

## Stage 6: Packaging, cron and live suite

**Goal**: A releasable 0.x with documentation and real-world verification.
**Success Criteria**: `cron install|uninstall` with the managed block and its end line; README with install commands for every sibling; `live` suite (forgectl read-only discovery on a public repository; a headless haiku implement stub through claude-session; the key-matching corpus); a macOS checklist; `config.example.yaml` validated in CI.
**Tests**: the cron block golden file (idempotent replace, an end-less block refused); live suite instructions; markdown lint.
**Status**: Not Started

## Version roadmap

- **0.x**: stages 0 to 6, released automatically from Conventional Commit PR titles. Breaking changes before 1.0 are `feat` commits whose title names the break.
- **1.0** requires: the live suite green against real implementations of every sibling at the pinned minimum versions; an interactive implement run observed end to end (auto-exit after `report done`, the trust dialog at a new worktree, launch from a jobsctl job without `TMUX` and `SSH_AUTH_SOCK`); GitLab discovery verified; a real repository rename and a real draft pull request becoming ready observed; the macOS checklist done by a human.
- **1.x (additive, one tracking issue each)**: a work-item `browse` TUI with one query language (designed with forgectl's lessons); the pr-watch early trigger; `match.component` once ticketctl exposes components; linking tickets to pull requests natively once ticketctl can; a gate-friendly `before_confirm` hook once ticketctl exposes it; a per-repository `sprint_board` auto-discovery; an agent branch field once agent-spawn exposes it; an optional `wtctl locate` without auto-clone for `validate`.
- **2.0**: nothing planned; no speculative work.
