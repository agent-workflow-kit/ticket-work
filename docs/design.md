# ticket-work: design

Status: designed (interface 0.1.0-design, 2026-11-13). The rules are in [`interface.md`](interface.md), the single normative source; this document records the decisions, the live-verification results, the modules and the test strategy, and links to the interface headings instead of restating its tables.

Section references (§N) point to `../awkit-docs/architecture.md` unless marked "design guide" (`../awkit-docs/design-guide.md`).

## Role and layer

Own the lifecycle of a worked ticket: claim, transition, launch an implement agent, link the pull requests, and follow them to done. Layer 3 (workflow). It works fully standalone at a terminal and from cron; it has no upward awareness. It is a skill-wrapper tool for the `implement-ticket` slot (§5.5, design guide §11) and keeps a pending store (design guide §4.4). Flow B of the architecture is §10.2; the commands are listed under [Commands](interface.md#commands).

## Uses

| Tool | Binding | Used for |
|---|---|---|
| ticketctl | A | live ticket reads (`get`, `whoami`), plans and writes (`transition`, `sprint add|remove`, `update`, `comment`), the restore |
| ticket-queue | A | `next --claim`, `claim` (with `--renew`), `claims --holder`, `release` (plain and `--failed`) |
| forgectl | A | discovery (`prs`), pull request state (`show`); minimum 0.52.0 |
| agent-spawn | A | `launch`, `resume`, `wait`, `list`, `show`, `label add|remove`, `teardown` |
| jobsctl | A, optional | the `tickets` queue (`add`, `show`, `retry`, `resolve`, `capacity`); without it the job command runs in the foreground |
| wtctl | A | `locate`, an early check at `start` that the repository resolves, before anything is changed |
| pr-watch | A, optional | an early-detection trigger only (`watch add`, `events`); off by default |

No binding is of type B or C: no alternative provider exists for any of these roles. ticketctl is the only ticket source (the architecture treats the ticket source as a tool role, not a skill slot). Each edge is declared in the README with its binding type.

## Decisions

| ID | Decision | Rationale | Interface |
|---|---|---|---|
| D-1 | ticket-work keeps its own SQLite store, one work item per ticket (`site:KEY`) with a coarse `phase` derived from the other tools' facts at each `sync` | pending confirmations, the previous status and sprint ids for a restore, the holder, the links and the applied events live nowhere else; everything external is re-read | [Work item and phases](interface.md#work-item-and-phases) |
| D-2 | Jira changes are applied at confirm time, before the job is enqueued; a job that ends before the agent launches triggers the restore | follows §10.2; a confirmation made at one time is applied at that time and the plan hash stays fresh; `start --auto` checks capacity first, so the gap is short | [Start order](interface.md#start-order), [Restore](interface.md#restore) |
| D-3 | The status map is an event → rule table per board: `to`, `from` (required for `started`), `resolution`, `confirm`, `comment`; no shipped status names; an event with no rule only fires hooks | resolves open topic 1; ticketctl picks transitions by target; a `from` guard (enforced with `--if-status`) stops accidental backward moves | [Status map](interface.md#status-map) |
| D-4 | The implement kind is trusted; the sandbox defaults to `off` and setting sources to `["project"]`; every safety setting is a config key; the agent opens the draft pull request itself; ticket-work verifies it | spike B: a sandboxed `dontAsk` run cannot reach `gh`, `ssh` or git identity, and `GH_TOKEN` is stripped from the agent's Bash environment; recorded deviations from design guide §11 | [Slot contract](interface.md#slot-contract) |
| D-5 | Linking has tiers: claimed (verified artifact URL), branch token (case-insensitive whole token, key from the ticket), title only (a candidate), manual; links store `pr_id` and `repo_id` | spike A: only 98 of 179 real pull requests carry a key in the branch, and a generic key pattern gives bogus keys from dependency-bot branches | [PR linking](interface.md#pr-linking) |
| D-6 | Preconditions are a closed set of named declarative checks plus the `pre-enqueue` hook; an unknown value fails; `start --auto` failures release with `--failed` | resolves open topic 2; a refusal names the rule; ticket-queue's auto-skip removes repeat offenders | [Preconditions](interface.md#preconditions) |
| D-7 | Stale work is detected and notified, never acted on, except that a diverged ticket releases the claim | resolves open topic 3; public defaults; teardown only after a merge | [Stale and diverged work](interface.md#stale-and-diverged-work) |
| D-8 | `pr_merged` is an aggregate: at least one merged and none open; a partial merge fires `post-status` only; teardown uses the last merged head | several pull requests per ticket | [Status map](interface.md#status-map), [Teardown](interface.md#teardown) |
| D-9 | `resume KEY` enqueues a job that resumes the same agent (`jobsctl retry --attempt N` for a held job); the job command is resume-aware and runs `launch --wait` or `resume --wait` | job-cap accounting (§9.2); the cancellation chain only works with `--wait` | [resume](interface.md#resume), [Job command](interface.md#job-command) |
| D-10 | Ordered repository rules per board; a deterministic branch name `<type>/<KEY>-<slug>` built by ticket-work | no untrusted text reaches the branch; the key is always a whole token | [Ticket to repository and branch](interface.md#ticket-to-repository-and-branch) |
| D-11 | One fenced prompt file (trusted facts outside the fences), a strictly validated artifact with a skill marker and a run token | a wrong skill name exits 0 `done` without an artifact (spike B); claude-session does not fence the prompt | [Slot contract](interface.md#slot-contract) |
| D-12 | forgectl is the truth; `sync` derives events by diffing stored per-pull-request facts; pr-watch is an optional trigger, off by default | spike A: forgectl has no history, so ticket-work stores last-seen facts and derives events by diffing; one `show` per linked pull request costs one request, so pr-watch is not needed for correctness | [Sync order](interface.md#sync-order) |
| D-13 | A pending start expires after 24 hours by default; `sync` renews the claim of a pending start | at most one pending start under `--auto`; the design guide's seven days would block automatic starts for a week | [Pending confirmations](interface.md#pending-confirmations) |
| D-14 | The restore is best-effort and never blind; failures set `restore_failed` | a closed sprint and a missing reverse transition are known failure modes | [Restore](interface.md#restore) |
| D-15 | No `browse` and no query language in 0.x; `list` and `show` with fixed filters | the dashboard consumes `list --json`; a work-item TUI is a 1.x item designed with forgectl's query-language lessons | [list and show](interface.md#list-and-show) |
| D-16 | A `confirm: ask` rule found by a non-TTY `sync` is a pending confirmation; `defaults.confirm: auto` replaces the seed's `auto_transition` | public default is show-and-confirm; automation never passes `--yes` | [Pending confirmations](interface.md#pending-confirmations) |
| D-17 | Ticket comments are off by default and follow the same `confirm` flow | ticketctl cannot link a pull request to a ticket (a 1.x item) and comments cannot be edited | [Ticket comments](interface.md#ticket-comments) |
| D-18 | `stop` ends ticket-work's activity and keeps the agent and worktree; `start KEY` re-adopts them | no stranded work, no second branch for one key | [stop](interface.md#stop) |
| D-19 | One instance per state directory; the holder is `ticket-work:<instance>`; `started.from` is mandatory so Jira's live status is the shared guard | ticket-queue claims are local; no cross-machine locking | [Residual risks](interface.md#residual-risks) |
| D-20 | Hooks: `pre-enqueue`, `pre-transition`, `pre-launch` (veto-capable) and `post-link`, `post-status`, `post-start-failed`, `post-pending`, `post-attention` (closed reasons), delivered at least once through an outbox | notifications need a closed reason to route on | [Hooks](interface.md#hooks) |

## Resolved open topics

1. Status map format and event mapping: D-3, [Status map](interface.md#status-map).
2. Preconditions: D-6, [Preconditions](interface.md#preconditions).
3. Stale pull requests: D-7, [Stale and diverged work](interface.md#stale-and-diverged-work).
4. Ticket state machine and persistence: D-1, [Work item and phases](interface.md#work-item-and-phases).

## Live verification

| ID | Question | Result | Used for |
|---|---|---|---|
| A1, A2 | what `forgectl prs` and `show` return | `prs --author me --state all --updated-since` works; list items lack `merged_at`, `merged_head_sha`, CI; no head-branch, label or merge-time filter | discovery and the read step |
| A3 | whole-token key matching | the case-insensitive token pattern; generic key patterns give bogus keys | D-5 |
| A4 | `merged_head_sha` | the final head (40 hex), not the squash commit; null when closed unmerged | [Teardown](interface.md#teardown) |
| A5 | event history | forgectl is state-only; draft-to-ready timing needs ticket-work's stored facts | D-12 |
| A6 | cost | `prs` 1 request per 100 items, `show` 1, `snapshot` 6, no output cap | [Sync order](interface.md#sync-order) |
| A7 | missing or renamed repository | `prs --repo` returns exit 0, empty, `complete: true`; `show` exits 10 | [PR linking](interface.md#pr-linking) |
| B1 | the `implement` kind | built in; trusted, sandbox off, inherits the environment; an unknown kind silently becomes the third-party-reading review profile | the kind check |
| B2, B3 | a headless end-to-end run | works; a wrong skill name exits 0 `done` with no artifact; there is no `--no-implicit-done` flag, so `report.implicit` must be checked | artifact validation |
| B4 | where branch and pull request URL live | only in the artifact; `status` has no such field | claims are verified |
| B5 | blocked and needs-input | both exit 13; `report.status` tells them apart; headless resume carries labels, profile and mode but not `--skill` | the job command and `resume` |
| B6 | the ticket in the prompt | verbatim in the prompt file, not fenced | fencing is ticket-work's job |
| B7 | secrets | `secret_env` strips a ticket token; Claude Code drops `GH_TOKEN` and `GITHUB_TOKEN` from the agent's Bash environment | D-4 |
| B8 | supervision | no interactive timeout by default; a pending run expires after 10 minutes; `--max-turns` maps to exit 16 | the job command |

Still to verify (live tests in the plan): an interactive implement run auto-exiting after `report done`; the trust dialog at a new worktree; GitLab repository-id discovery; a real repository rename; a real draft pull request becoming ready. The conservative default for each is documented in the interface.

## Modules

Package `ticket_work` (`src/ticket_work/`). One gateway module for every subprocess and HTTP call.

| Module | Responsibility |
|---|---|
| `cli.py` | argparse commands, global flags, exit mapping |
| `config.py` | loading, drop-ins, validation, precedence |
| `store.py` | SQLite (WAL), migrations, work items, links, pending, applied events, outbox, leases |
| `gateway.py` | the only place that spawns processes; fakes plug in here |
| `boards.py` | repository rules, branch name derivation |
| `preconditions.py` | the closed check set |
| `statusmap.py` | rule loading and event evaluation |
| `events.py` | deriving events from stored facts and new facts |
| `linking.py` | key matching, tiers, verification through forgectl |
| `start.py` | the start order |
| `job.py` | the job command |
| `sync.py` | the sync order |
| `pending.py` | pending records, confirm, reject, expiry |
| `restore.py` | the restore flow |
| `teardown.py` | teardown after a merge |
| `prompt.py` | fencing and prompt files |
| `artifact.py` | artifact validation |
| `hooks.py`, `outbox.py` | hook execution and at-least-once delivery |
| `audit.py` | audit and log records |
| `leases.py` | lease locks |
| `plugin/` | the bundled plugin, skill, marker reference file and permission profile |

## Data model

`state.db` tables: `meta` (schema version), `work_items`, `links` (keyed by work id and `pr_id`), `pending`, `events` (applied and declined event keys), `outbox` (hook events and audit pairs awaiting delivery), `leases`. All access is in transactions; a `sync` writes per work item. The store is additive-only across versions.

## Concurrency

Leases follow design guide §4.3 (see [Concurrency](interface.md#concurrency)). The claim row in ticket-queue arbitrates claims; the live status check and `--if-status` arbitrate the ticket; the job unique key arbitrates jobs.

## Error handling

Every lower tool failure is wrapped as exit 12 with `tool`, `lower_code` and `lower_error` (design guide §4.2). A failure inside `sync` is recorded per work item (`sync_failed`) and the other items continue. Idempotent steps (restore, teardown, claim renewal, release) can run again after a crash; a work item in phase `starting` with no job is repaired by the next `sync`.

## Test strategy

- All subprocess calls go through `gateway.py`; fakes of every sibling live in `tests/fakebin/` with their JSON outputs validated against the sibling schemas copied into `tests/` and pinned to a version.
- Golden-file tests for every `--json` output, hook payloads, audit and log records, the generated branch names and the prompt file.
- Process tests for the job command (launch, resume, wait, held, cancel, each agent outcome) and for the start order with injected failures after each step (the restore flow).
- Property tests for the key matcher, the slug derivation and the fencing function (`</untrusted` neutralization).
- Spike regressions, each a test: the key matching table of spike A3; an empty `prs` for a missing repository is not "absent"; `merged_head_sha` is passed to teardown; a missing skill marker, `report.implicit: true` and a wrong skill name fail the start; an unknown kind warning is fatal.
- `live` tests (deselected by default, never in CI): forgectl discovery against a public repository with read-only calls; a headless haiku implement stub through claude-session.
- `make verify` runs ruff, pyright, pytest and markdown lint.

## Dependencies of the tool itself

`pyyaml` (config; the standard library cannot read YAML) and `pydantic` (config validation), as every tool of the set; everything else is the standard library (`argparse`, `sqlite3`, `subprocess`). No TUI in 0.x.

## Platforms

Linux, WSL and macOS; tmux only for interactive agents through agent-spawn.
