# ticket-work: design

Status: designed (interface 0.1.0-design, 2026-11-13). The rules are in [`interface.md`](interface.md), the single normative source; this document records the decisions, the live-verification results, the modules and the test strategy, and links to the interface headings instead of restating its tables.

Section references (§N) point to `../awkit-docs/architecture.md` unless marked "design guide" (`../awkit-docs/design-guide.md`).

## Role and layer

Own the lifecycle of a worked ticket: claim, transition, launch an implement agent, link the pull requests, and follow them to done. Layer 3 (workflow). It works fully standalone at a terminal and from cron; it has no upward awareness. It is a skill-wrapper tool for the `implement-ticket` slot (§5.5, design guide §11) and keeps a pending store (design guide §4.4). Flow B of the architecture is §10.2; the commands are listed under [Commands](interface.md#commands).

## Uses

| Tool | Binding | Used for |
|---|---|---|
| ticketctl | A | live ticket reads (`get --fields ... --comments`, `whoami`), plans and writes (`transition`, `sprint add|remove`, `update`, `comment`), the restore |
| ticket-queue | A | `next --claim`, `claim` (with `--renew` and `--label`), `claims --holder`, `release` (plain and `--failed`) |
| forgectl | A | discovery (`prs`), pull request state (`show`), the host login (`whoami`), the idle signal (`snapshot`); minimum 0.52.0 |
| agent-spawn | A | `launch` (with `--dry-run` as a kind check), `resume`, `wait`, `list`, `show`, `label add|remove`, `teardown` |
| jobsctl | A | the `tickets` queue (`add`, `show <id>`, `cancel`, `retry`, `resolve`, `capacity`); required for `start --auto`, optional otherwise: without it a human `start` runs the job command in the foreground |
| wtctl | A | `locate`, an early check at `start` that the repository resolves, before anything is changed; `show`, for agent adoption |

No binding is of type B or C: no alternative provider exists for any of these roles. ticketctl is the only ticket source (the architecture treats the ticket source as a tool role, not a skill slot). pr-watch is not used in 0.x: `sync` reads every linked pull request itself, and the harness may trigger `ticket-work sync` on a pr-watch event. Each edge is declared in the README with its binding type.

## Decisions

| ID | Decision | Rationale | Interface |
|---|---|---|---|
| D-1 | ticket-work keeps its own SQLite store, one work item per ticket (`site:KEY`) with a coarse `phase` derived from the other tools' facts at each `sync` | pending confirmations, the previous status and sprint ids for a restore, the holder, the links and the applied events live nowhere else; everything external is re-read | [Work item and phases](interface.md#work-item-and-phases) |
| D-2 | Jira changes are applied at confirm time, after a write-ahead record (phase `applying`), before the job is enqueued; a job that ends before any agent run triggers the restore | follows §10.2; a confirmation made at one time is applied at that time and the plan hash stays fresh; `start --auto` checks capacity first, so the gap is short; the write-ahead record closes the crash window between the writes and the store | [Start order](interface.md#start-order), [Restore](interface.md#restore) |
| D-3 | The status map is an event → rule table per board: `to`, `from` (required for `started`), `resolution`, `confirm`, `comment`, `assign` (`me` only); no shipped status names; an event with no rule only fires hooks; events fire once or by key and failures are classed | resolves open topic 1; ticketctl picks transitions by target; a `from` guard (enforced with `--if-status`) stops accidental backward moves | [Status map](interface.md#status-map), [Events](interface.md#events), [Rule fields](interface.md#rule-fields) |
| D-4 | The implement kind is trusted; the sandbox defaults to `off` and setting sources to `["project"]`; every safety setting is a config key; the agent opens the draft pull request itself; ticket-work verifies it; the agent environment is a fixed base plus `agent.env_allowlist`, never `jobs.pass_env`; unattended runs follow D-24 | spike B: a sandboxed `dontAsk` run cannot reach `gh`, `ssh` or git identity, and `GH_TOKEN` is stripped from the agent's Bash environment; recorded deviations from design guide §11 | [Slot contract](interface.md#slot-contract), [Unattended runs](interface.md#unattended-runs) |
| D-5 | Linking has tiers: claimed (verified artifact URL), branch (the exact recorded branch first, then a case-insensitive whole token of one active work item's key; an ambiguous token is a candidate), title only (a candidate), manual; only counting pull requests drive events (D-27); links store `pr_id` and `repo_id`; the `pr=` agent label appears after the first `sync` that links the pull request | spike A: only 98 of 179 real pull requests carry a key in the branch, and a generic key pattern gives bogus keys from dependency-bot branches | [PR linking](interface.md#pr-linking) |
| D-6 | Preconditions are a closed set of named declarative checks plus the `pre-enqueue` hook; an unknown value fails; `start --auto` failures release with `--failed` | resolves open topic 2; a refusal names the rule; ticket-queue's auto-skip removes repeat offenders | [Preconditions](interface.md#preconditions) |
| D-7 | Stale work is detected and notified, never acted on, except that a diverged ticket releases the claim; divergence is judged only for active phases and `done` with a merged counting pull request is the normal path; the idle signal is `activity_at` | resolves open topic 3; public defaults; teardown only after a merge | [Stale and diverged work](interface.md#stale-and-diverged-work) |
| D-8 | `pr_merged` is an aggregate over counting pull requests with an agent condition: at least one merged, none open, the agent finished; a partial merge fires `post-status` (`pr_merged_partial`) only; cleanup waits for the rule outcome and tears down the one stored agent with the merged head of the pull request on the recorded branch | several pull requests per ticket; a merge into a scratch branch must not mark the ticket done | [Events](interface.md#events), [Teardown](interface.md#teardown) |
| D-9 | `resume KEY` enqueues a job that resumes the same agent (`jobsctl retry --attempt N` for a held job); the job command is resume-aware, runs `launch --dry-run` as a kind check, then `launch --wait` or `resume --wait`, and classifies every agent-spawn outcome by one table | job-cap accounting (§9.2); the cancellation chain only works with `--wait` | [resume](interface.md#resume), [Job command](interface.md#job-command) |
| D-10 | Ordered repository rules per board (one board per site; `match` keys `label`, `project`, `epic`, `issue_type`); a deterministic branch name `<type>/<KEY>-<slug>` built by ticket-work, whose slug drops key-like token pairs | no untrusted text reaches the branch; the key is always a whole token and no other key can appear in it | [Ticket to repository and branch](interface.md#ticket-to-repository-and-branch) |
| D-11 | One fenced prompt file (trusted facts outside the fences), a strictly validated artifact with a skill marker and a run token; the prompt is built at every launch or resume, and the token is per work item | a wrong skill name exits 0 `done` without an artifact (spike B); claude-session does not fence the prompt | [Slot contract](interface.md#slot-contract) |
| D-12 | forgectl is the truth; `sync` derives events by diffing stored per-pull-request facts; there is no pr-watch trigger in 0.x | spike A: forgectl has no history, so ticket-work stores last-seen facts and derives events by diffing; one `show` per linked pull request costs one request, so pr-watch is not needed for correctness | [Sync order](interface.md#sync-order), [Discovery and read](interface.md#discovery-and-read) |
| D-13 | A pending start expires after 24 hours by default; `sync` renews the claim of a pending start; expiry runs in `sync` and the pending phase ends in `failed`; `start --auto` counts the open pending starts against `start.max_pending` and capacity | at most one pending start under `--auto`; the design guide's seven days would block automatic starts for a week | [Pending confirmations](interface.md#pending-confirmations) |
| D-14 | The restore is best-effort and never blind; it runs only when no agent run ever started, from `start`, the job command and the `sync` repair step; each step is guarded by the live value the start set and by the stored step status; failures set `restore_failed` | a closed sprint and a missing reverse transition are known failure modes; basis against design guide §4.4: a compensating action of a start a human accepted, guarded, under the `restore_on_failure` opt-in | [Restore](interface.md#restore) |
| D-15 | No `browse` and no query language in 0.x; `list` and `show` with fixed filters | the dashboard consumes `list --json`; a work-item TUI is a 1.x item designed with forgectl's query-language lessons | [list and show](interface.md#list-and-show) |
| D-16 | A `confirm: ask` rule found by a non-TTY `sync` is a pending confirmation; `defaults.confirm: auto` replaces the seed's `auto_transition`; one confirmation matrix covers actor, TTY, `--yes`, rule and enforced gate; `confirm` re-plans and compares the stored hashes | public default is show-and-confirm; automation never passes `--yes` | [Pending confirmations](interface.md#pending-confirmations), [Confirmation matrix](interface.md#confirmation-matrix) |
| D-17 | Ticket comments are off by default and follow the same `confirm` flow; the dedupe key is a hash and the comment is posted by `sync` only (`link` never posts) | ticketctl cannot link a pull request to a ticket (a 1.x item) and comments cannot be edited | [Ticket comments](interface.md#ticket-comments) |
| D-18 | `stop` ends ticket-work's activity and keeps the agent and worktree; `start KEY` re-adopts them; re-adopt skips `started.from` and changes nothing on the ticket | no stranded work, no second branch for one key | [stop](interface.md#stop) |
| D-19 | One instance per state directory; the holder is `ticket-work:<instance>`; the claim carries the label `store=<store id>` (two state directories on one host still need different `instance` values, because the holder is the same string); `started.from` is mandatory so Jira's live status is the shared guard | ticket-queue claims are local; no cross-machine locking | [Residual risks](interface.md#residual-risks) |
| D-20 | Hooks: `pre-enqueue`, `pre-transition`, `pre-launch` (veto-capable) and `post-link`, `post-status`, `post-start-failed`, `post-pending`, `post-attention` (closed reasons, one entry per reason in an attention set), delivered at least once through an outbox; payloads carry a `dedupe_key` where relevant | notifications need a closed reason to route on | [Hooks](interface.md#hooks), [Attention reasons](interface.md#attention-reasons) |
| D-21 | Leases protect short critical sections; a run is identified by the stored job id and agent-spawn state | a lease held for a whole run blocks `sync`, `link` and `confirm` for hours; takeover only when the holder is dead, never on expiry alone, because a suspended machine keeps its PIDs | [Concurrency](interface.md#concurrency) |
| D-22 | The stored plan hashes are what the human accepted | `confirm` re-plans and compares every step hash; a difference supersedes the record with a new pending one | [Confirmation matrix](interface.md#confirmation-matrix) |
| D-23 | The agent id is adopted by verified labels; `launch --wait` is kept | `launch --wait` prints the id only at the end; the cancellation chain (a `cancel --force` reaching the agent) only works with `--wait` because `wait` never forwards a signal; labels only find candidates and every action uses the stored id | [Agent adoption](interface.md#agent-adoption) |
| D-24 | Unattended runs (`start --auto`, headless) take comments only from trusted authors, need a trusted reporter and load no project settings unless a repository opts in | ticket text is third-party text and the implement agent is trusted and unsandboxed; this changes the setting-sources default for unattended runs only (user decision, pass 1) | [Unattended runs](interface.md#unattended-runs) |
| D-25 | Event model: once-per-item keys, ordered catch-up, rule hash and seen status for re-evaluation, permanent versus transient failures | an event must not fire twice and a pull request opened and merged between two syncs must move the ticket once | [Events](interface.md#events) |
| D-26 | Credentials never reach the agent through `jobs.pass_env` | the job needs `TMUX` and `SSH_AUTH_SOCK` for its own tool calls; the agent gets only a fixed base plus `agent.env_allowlist`; one sanitizer covers human output | [Slot contract](interface.md#slot-contract), [Output sanitizing](interface.md#output-sanitizing) |
| D-27 | Counting pull requests | a pull request counts only when it is not from a fork and its base chain ends at the work item's base (a manual link counts); only counting pull requests drive events, staleness and teardown | [PR linking](interface.md#pr-linking) |
| D-28 | Lower exits are mapped in one table | every lower exit maps to a ticket-work exit, reason, retry class and attention; lower exits 21 and 22 never become ticket-work's | [Lower tool exits](interface.md#lower-tool-exits) |

## Resolved open topics

1. Status map format and event mapping: D-3, [Status map](interface.md#status-map).
2. Preconditions: D-6, [Preconditions](interface.md#preconditions).
3. Stale pull requests: D-7, [Stale and diverged work](interface.md#stale-and-diverged-work).
4. Ticket state machine and persistence: D-1, [Work item and phases](interface.md#work-item-and-phases).

## Deviations from the approved session text

S-9: the job unique key is `ticket:<site>:<KEY>` (not `ticket:<KEY>`) and the job is read by its stored id, as approved. S-10: `match.component` is dropped because ticketctl has no component property; a refusal after a claim under `start --auto` releases with `--failed` (a plain release would let cron retry the same ticket forever). S-11 and S-4: unattended runs have a trusted-reporter rule, trusted-author comments and empty setting sources by default (D-24). S-12: pr-watch is not used in 0.x. S-8: `pr_merged` counts only counting pull requests and needs the agent condition (D-8). S-14: the restore runs only when the agent never ran, with guards (D-14). S-18: re-adopt wording (D-18). S-13: a rejected or expired pending start ends in phase `failed`.

## Live verification

| ID | Question | Result | Used for |
|---|---|---|---|
| A1, A2 | what `forgectl prs` and `show` return | `prs --author me --state all --updated-since` works; list items lack `merged_at`, `merged_head_sha`, CI; no head-branch, label or merge-time filter | discovery and the read step |
| A3 | whole-token key matching | the case-insensitive token pattern; generic key patterns give bogus keys | D-5 |
| A4 | `merged_head_sha` | the final head (40 hex), not the squash commit; null when closed unmerged | [Teardown](interface.md#teardown) |
| A5 | event history | forgectl is state-only; draft-to-ready timing needs ticket-work's stored facts | D-12 |
| A6 | cost | `prs` 1 request per 100 items, `show` 1, `snapshot` 6, no output cap | [Sync order](interface.md#sync-order) |
| A7 | missing or renamed repository | `prs --repo` returns exit 0, empty, `complete: true`; `show` exits 10 | [PR linking](interface.md#pr-linking) |
| A8 | rename recovery by `repo_id` | still to verify (a host-wide listing matched by `repo_id` and `pr_id`) | [Discovery and read](interface.md#discovery-and-read) |
| A9 | `snapshot --no-bodies` as the idle signal | still to verify (forgectl 0.52.0 covers the flag) | [Discovery and read](interface.md#discovery-and-read) |
| B1 | the `implement` kind | built in; trusted, sandbox off, inherits the environment; an unknown kind silently becomes the third-party-reading review profile | the kind check, now also a `launch --dry-run` before every launch |
| B2, B3 | a headless end-to-end run | works; a wrong skill name exits 0 `done` with no artifact; there is no `--no-implicit-done` flag, so `report.implicit` must be checked | artifact validation |
| B4 | where branch and pull request URL live | only in the artifact; `status` has no such field | claims are verified |
| B5 | blocked and needs-input | both exit 13; `report.status` tells them apart; headless resume carries labels, profile and mode but not `--skill` | the job command and `resume` |
| B6 | the ticket in the prompt | verbatim in the prompt file, not fenced | fencing is ticket-work's job |
| B7 | secrets | `secret_env` strips a ticket token; Claude Code drops `GH_TOKEN` and `GITHUB_TOKEN` from the agent's Bash environment | D-4 |
| B8 | supervision | no interactive timeout by default; a pending run expires after 10 minutes; `--max-turns` maps to exit 16 | the job command |

Still to verify (live tests in the plan): an interactive implement run auto-exiting after `report done`; the trust dialog at a new worktree; GitLab repository-id discovery; a real repository rename (recovery by `repo_id`); a real draft pull request becoming ready; an interactive launch from a jobsctl job without `TMUX` and `SSH_AUTH_SOCK` (which names must be passed); a headless project-settings load without a trust dialog (on a fake repository); `wtctl locate` auto-clone during `--dry-run`; a claim re-take after a lapse; `snapshot --no-bodies` as the idle signal; a `done` report with an empty `prs`. The conservative default for each is documented in the interface.

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
| `job.py` | the job command and the stored settings snapshot |
| `adopt.py` | agent adoption by verified labels |
| `attention.py` | the attention set, its set and clear rules |
| `claims.py` | claim, renewal, re-take, release table, orphan sweep |
| `exits.py` | the lower-exit mapping table |
| `sanitize.py` | the one output sanitizer |
| `sync.py` | the sync order |
| `pending.py` | pending records, confirm, reject, expiry |
| `restore.py` | the restore flow |
| `teardown.py` | teardown after a merge |
| `prompt.py` | fencing, run token and prompt file hygiene (0700 directories, 0600 `O_EXCL|O_NOFOLLOW` files) |
| `artifact.py` | artifact validation |
| `hooks.py`, `outbox.py` | hook execution and at-least-once delivery |
| `audit.py` | audit and log records |
| `leases.py` | lease locks |
| `plugin/` | the bundled plugin, skill, marker reference file and permission profile |

## Data model

`state.db` tables: `meta` (schema version, store id, the `sync_rerun` flag), `work_items`, `links` (keyed by work id and `pr_id`), `pending`, `events` (event, event key, outcome, reason, rule hash, seen status), `outbox` (hook events and audit pairs awaiting delivery), `leases` (kind `sync` or `ticket`, key, holder PID, process start time, expiry, generation). A work item stores, beyond its identity and phase: `steps` (the write-ahead step list), `previous`, `started_status`, `last_artifact`, the `settings` snapshot, `run_token`, the stored job and agent ids, the attention set and `store_id` references. All access is in transactions; a `sync` writes per work item. The store is additive-only across versions.

## Concurrency

Leases follow design guide §4.3 (see [Concurrency](interface.md#concurrency) and D-21). There are two kinds: the sync lease, one row held by `sync` for its run, and the ticket lease, one row per work id held only during a store transaction, a lower-tool call for that ticket or the `start` dialog, never across `agent-spawn launch|resume|wait`. A lease is taken over only when its holder is dead (PID gone or start time changed), never on expiry alone. A second `sync` exits 0 and sets `sync_rerun`; the running `sync` repeats once. The claim row in ticket-queue arbitrates claims; the live status check and `--if-status` arbitrate the ticket; the job unique key arbitrates jobs.

## Error handling

Every lower tool failure is wrapped as exit 12 with `tool`, `lower_code` and `lower_error` (design guide §4.2). A failure inside `sync` is recorded per work item (`sync_failed`) and the other items continue. Lower exits are mapped by one table ([Lower tool exits](interface.md#lower-tool-exits), D-28). Idempotent steps (restore, teardown, claim renewal, release) can run again after a crash; the `sync` repair step restores a work item stuck in `applying`, or in `starting` with no job, once its ticket lease is dead and a grace has passed (D-14).

## Test strategy

- All subprocess calls go through `gateway.py`; fakes of every sibling live in `tests/fakebin/` with their JSON outputs validated against the sibling schemas copied into `tests/` and pinned to a version.
- Golden-file tests for every `--json` output, hook payloads, audit and log records, the generated branch names and the prompt file.
- Process tests for the job command (launch, resume, wait, held, cancel, each row of the outcome table) and for the start order with injected failures after each step (the restore flow); the crash-window table as process tests (a kill after the claim, after each write, after the record, after the job add before its id is stored, after the launch started); lease takeover tests (a dead holder only).
- Scenario tests for events: opened and merged in one `sync`; a `from` mismatch then a status change; a permanent failure then a rule edit; a second linked pull request does not re-fire `pr_opened`.
- Property tests for the key matcher, the slug derivation (the three slug vectors of the interface; no output matches `[a-z]+-[0-9]+`), the fencing function (`</untrusted`, `</UNTRUSTED` and `</ untrusted` neutralization) and the closed list of environment variables.
- Golden tests for the job argv, the prompt (and a file mode test: 0600 files in 0700 directories) and the output sanitizer.
- A sample-validation test: sample outputs and hook payloads validated against `schemas/`.
- Spike regressions, each a test: the key matching table of spike A3; an empty `prs` for a missing repository is not "absent"; `merged_head_sha` is passed to teardown; a missing skill marker, `report.implicit: true` and a wrong skill name fail the start; an unknown kind warning is fatal.
- `live` tests (deselected by default, never in CI): forgectl discovery against a public repository with read-only calls; a headless haiku implement stub through claude-session.
- `make verify` runs ruff, pyright, pytest and markdown lint.

## Dependencies of the tool itself

`pyyaml` (config; the standard library cannot read YAML) and `pydantic` (config validation), as every tool of the set; everything else is the standard library (`argparse`, `sqlite3`, `subprocess`). No TUI in 0.x.

## Platforms

Linux, WSL and macOS; tmux only for interactive agents through agent-spawn.
