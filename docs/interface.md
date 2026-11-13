# ticket-work: interface

Status: 0.1.0-design (2026-11-13). This document is the single normative source for ticket-work's rules. `design.md`, the README and the architecture link to its headings and never restate its tables. Section references (architecture §N, design guide §N) point to `../awkit-docs/architecture.md` and `../awkit-docs/design-guide.md`.

ticket-work owns the lifecycle of a worked ticket: it claims a ticket, applies the board's start changes (assignment, sprint, status) after a confirmation, launches an implement agent in its own worktree, links the agent's pull requests to the ticket, applies a per-board status map as those pull requests move, and tears the work down after the merge. It is a workflow tool (layer 3) and a skill wrapper for the `implement-ticket` slot (design guide §11). It works standalone from a terminal and from cron; it never depends on the harness.

## Overview

- **Work item.** One record per worked ticket. The work id is `<site>:<KEY>` as created and never changes; `key` is the current canonical key and `requested_keys` lists every earlier or requested key (a moved ticket). Everything derived from a key at creation (the job unique key, the agent and job labels, the branch) stays as created; every lookup (adoption, label search, branch token matching, artifact `ticket` validation) uses the union of `key` and `requested_keys`. The `site` is a config site name (at most 32 characters); the key follows ticketctl's grammar; the whole id fits `^[A-Za-z0-9._:-]{1,128}$` and contains neither whitespace nor `/`. The record lives in ticket-work's own store (`state.db`); everything another tool owns (the claim, the ticket, the pull request, the job, the agent) is re-read from that tool on each `sync`. The store holds only what no other tool owns: the previous status, assignee and sprint ids for a restore, the write-ahead step list, the pending confirmations, the claim holder, the job id, the agent id, the linked pull requests with their last-seen facts, the applied events and the attention reasons.
- **Board.** A named config entry with a ticketctl `site`, the rules that map a ticket to a repository, the branch naming, the preconditions and the status map. A site has exactly one board. ticket-work boards are bound to ticket-queue boards by `queue_board` (optional), never by name.
- **Link.** The relation between a work item and a pull request, recorded with the evidence that justified it (`tier`).
- **Pending confirmation.** A recorded action that needs a human (design guide §4.4).
- **Holder.** The opaque claim holder `ticket-work:<instance>` (see Configuration, `instance`).

pr-watch is not used in 0.x: `sync` reads the pull requests itself (one `show` per linked pull request), so an early check is `ticket-work sync` itself; the harness triggers it on a pr-watch event (architecture section 7.5).

## Commands

```text
ticket-work start [KEY] [--auto] [--board B] [--skill S] [--mode interactive|headless] [--sandbox LEVEL] [--dry-run] [--yes]
ticket-work resume KEY [--mode interactive|headless] [--prompt-file F]
ticket-work sync [KEY]
ticket-work list [--board B] [--phase P]... [--needs-attention] [--label k=v]... [--pr PR] [--all]
ticket-work show KEY
ticket-work stop KEY
ticket-work link KEY PR
ticket-work unlink KEY PR
ticket-work pending [--all]
ticket-work confirm ID
ticket-work reject ID
ticket-work cron install|uninstall [--sync-interval D] [--with-start [--start-interval D]]
ticket-work export [--since T] [--after-seq N] [--to PATH]
ticket-work prune [--older-than D] [--dry-run]
ticket-work validate [--probe]
ticket-work _job WORK_ID            (internal; run by the job, see Job command)
```

`KEY` is a ticket key or `site:KEY`; a bare key that matches work items or tickets on several sites exits 21 (`ambiguous_key`, `details.candidates`). `PR` is a URL or `host/<full project path>#N`. Ticket keys follow ticketctl's grammar and are printed upper-case.

### Global flags

`--json`, `--config PATH`, `--verbose`, `--quiet` (with `--verbose`: exit 2 `invalid_combination`), `--dry-run`, `--yes`, `--actor ACTOR`, `--decision-id ID` (repeatable), `--hook NAME=CMD` (repeatable), `--version`.

- `--dry-run` applies to every command that changes state or contacts another tool for a write: it stores nothing (including cursors), takes no lease and prints what would happen. `sync --dry-run` prints the events and rules that would be evaluated; `resume`, `confirm`, `stop`, `link` and `unlink` print their plan.
- `--actor` follows ticketctl's grammar `^(human|auto):[A-Za-z0-9._@-]{1,64}$`. The default is `human:<me.name>` when stdin and stderr are TTYs and `/dev/tty` opens, otherwise `auto:unknown`. `cron install` writes entries that pass `--actor auto:cron`.
- `--yes` means the caller confirmed in its own dialog; it skips ticket-work's own confirmation dialog (Confirmation matrix). It is accepted only with a human actor; with an `auto:` actor it exits 2 (`human_only`). It never bypasses a precondition, a gate or a refusal. Automation never passes it (design guide §4.4).
- `--hook NAME=CMD` adds a hook for one invocation. It is accepted by `start`, `resume`, `confirm`, `stop`, `sync`, `link` and `unlink`; it is not carried into a job (the `pre-launch` hook of a job comes from config only) and is not config.
- Untrusted text never travels only in argv: `resume --prompt-file` takes a file or `-`. At most one `-` source per command (exit 2 `stdin_conflict`).
- `--config PATH` loads only that file (no drop-ins). It is forwarded in the job argv when a start used it.

### start

`start KEY` claims that ticket; `start` with no key takes the top eligible ticket. `--board B` names a ticket-work board and limits the choice to that board's tickets: it passes `--board <queue_board>` to `ticket-queue next`, requires that `queue_board` is set (otherwise exit 2 `invalid_combination`), and the chosen ticket's site must equal B's site. `--skill`, `--mode` and `--sandbox` override the `agent.*` config keys for this start and are stored on the work item.

`start --auto` is the cron form: it is the only form that may run without a human. It requires jobsctl, applies the capacity gate of Start order step 1, starts at most one ticket per run (one claim, one pending start at most), records a pending start unless the rule's `confirm` is `auto`, and never prompts.

The order of every start is fixed (Start order). A start that cannot proceed releases its claim (Claim release rules) and exits with the refusal. Output: the start result object (Objects).

Exit codes: 0 started (job enqueued, or the pending start was confirmed in the same call); 2 usage (`invalid_combination`, `human_only`, `invalid_config`, `missing_option`); 10 the ticket was not found; 11 a `pre-enqueue` hook vetoed; 12 a lower tool failed; 13 a pending start was recorded or a hook escalated; 20 refused (`precondition_failed`, `unmapped`, `already_started`, `claimed`, `untrusted_reporter`, `declined`, `claim_lost`, or a lower reason passed through); 21 ambiguous key; 22 `nothing_to_start`.

### resume

`resume KEY` continues the agent of a work item that is not finished. It requires phase `starting`, `working` or `in_review` and a parked agent (a live agent exits 20 `live`); when no agent id is stored it first runs Agent adoption. It enqueues a job whose command resumes the same agent. `--mode` defaults to the mode of the agent's last non-promotion run; a human answering a blocked headless agent passes `--mode interactive`. `--prompt-file` carries the human's answer (fenced by ticket-work like every untrusted text, see Slot contract); `-` reads stdin.

`resume` that finds the claim lapsed (`ticket-queue claims` has no claim for the holder, or a renewal answers `not_held`) takes a new claim (`claim KEY --holder H --label store=<store id>`); only a refusal (the ticket is claimed by another holder, `done`, `gone`, `skipped`, `hidden`) exits 20 `claim_lost`.

If a job for this work item is held (hold reason `exit_13`), `resume` continues it with `jobsctl retry <id> --attempt N` (same job id); otherwise it adds a new job with the same unique key (a terminal holder of the key does not block) and clears the attention `job_failed`. Without jobsctl it runs the job command in the foreground and exits as `start` does.

Exit codes: 0 enqueued; 2; 10 no such work item; 11 a `pre-launch` veto (a foreground run only; otherwise the veto is raised later, in the job); 12 a lower tool failed; 13 a pending launch recorded (a foreground run only; otherwise raised in the job); 20 refused (`live`, `not_active`, `claim_lost`); 21 ambiguous key.

### sync

`list` and `show` read only the store; `sync` is the periodic command and the only one that reads every tool. It is idempotent, safe under cron and takes a lease (Concurrency). The order is fixed (Sync order). `sync KEY` restricts every step to that work item and its repository, reads and updates that item's facts, and never advances a discovery cursor. `sync --dry-run` stores nothing (no cursor, no facts, no events) and prints the events and rules that would be evaluated.

A human `sync` at a TTY shows all due `confirm: ask` plans together and asks once: a yes applies them all, a no records nothing (the events stay due and are evaluated again at the next `sync`). Without a TTY, or with an `auto:` actor, each due plan becomes a pending confirmation.

Output: the sync report object. Exit codes: 0 (including "already running", `already_running: true`); 1 internal; 2 usage; 12 a lower tool failed (`lower_failed` for the whole run, `partial_results` for part of it; the report is printed with `partial: true` and the envelope's `details.errors`; the other items were still processed).

### list and show

`list` and `show` read only the store; they contact no other tool and run no hook. `list --json` prints `{"items": [<work item summary>...], "count": N}` ordered by `updated` descending. Without `--all`, items in phase `merged`, `stopped` or `failed` older than 24 hours are omitted unless they have an attention reason or an outstanding cleanup (`cleanup.teardown` `pending` or `refused`); `--needs-attention` ignores the age rule. `--board B` names a ticket-work board. `--phase` is repeatable (OR); `--label` filters the work item's `labels`; `--label` and `--pr` are ANDed; `--pr PR` matches a link. `show KEY` prints the work item with its links, pending confirmations, last report summary (untrusted) and the last 20 events. Human output of untrusted fields is sanitized (Output sanitizing).

Exit codes: `list` 0, 2; `show` 0, 2, 10 (the key has no work item), 21.

### stop

`stop KEY` ends ticket-work's activity on a ticket. It first adopts the agent when no id is stored (Agent adoption). It refuses (exit 20 `live`) while the agent is live or the job is `running`; nothing overrides `live` (stop the agent with `agent-spawn stop` first). Otherwise by phase: `pending` rejects the pending start (as `reject`: claim released plainly, phase `failed`); `applying` exits 20 `not_active` (the repair step handles it); `merged` exits 20 `not_active`; `failed` and `stopped` exit 0 `unchanged`; for `starting`, `working` and `in_review` it cancels a queued or held job (`jobsctl cancel <job id>`; plain cancel), applies the `stopped` rule of the board's status map if there is one (with that rule's `confirm`), releases the claim with a plain `release`, sets phase `stopped` and clears every attention reason the item holds except `teardown_refused`. If the `stopped` rule needs a confirmation, a pending record of action `stop` is created, the claim stays held, the phase is unchanged and the command exits 13; the item becomes `stopped` only when the record is confirmed (rejecting it leaves the item active; expiry drops it). After `stopped`, `sync` records pull request facts for display but makes no transition, comment or teardown for the item and renews no claim. The agent and the worktree stay parked; removing them is `agent-spawn teardown`, a separate step (`--force` there is human-only).

`start KEY` on a `stopped` item is a re-adopt (Re-adopt and restart).

Exit codes: 0; 2; 10; 12 (a lower tool failed); 13; 20 (`live`, `not_active`).

### link and unlink

`link` and `unlink` require a human actor (exit 2 `human_only`; advisory, like ticketctl's). Both are allowed in every phase except `pending` and `applying` (exit 20 `not_active`), both support `--dry-run`, and both are idempotent: a `link` of an already linked pull request, and an `unlink` of an unknown link, exit 0 with `changed: false`.

`link KEY PR` records a manual link (tier `manual`) after checking through forgectl `show` and `forgectl whoami` that the pull request is authored by the user's own account, lies in a repository the board maps, and is not already linked to another work item. Refusals (exit 20, reason `not_linkable`, `details.why`): `author_not_me`, `author_unknown`, `repo_not_mapped`, `linked_elsewhere`, `not_found`, `fork`. A candidate (tier `title`, or an ambiguous `branch` token) is promoted by `link`. A `link` of a pull request that does not target the base chain is allowed (a human decided) and counts. `link` adds the `pr=` label to the stored agent (PR linking), fires `post-link` and writes an audit record. `link` never posts a comment itself (so a manual link and the next `sync` cannot post twice).

`unlink KEY PR` removes the link, removes the `pr=` label, and marks the pull request `ignored` for this work item so discovery never links it again; an ignored pull request is removed from the counting set.

Exit codes: `link` 0, 2, 10, 12, 20, 21; `unlink` 0, 2, 10, 12, 21.

### pending, confirm and reject

Design guide §4.4 applies. `pending` lists unresolved pending confirmations (`--all` includes resolved and expired ones until pruned); a record past its expiry is listed as `expired`. `confirm ID` on a TTY shows the stored `details.changes` and asks (the answer is read from `/dev/tty`); `--yes` with a human actor skips the dialog (the dashboard route); without a TTY and without `--yes` it exits 2 `human_only`. This is advisory, like ticketctl's confirmation (Residual risks). `reject ID` needs a human actor with the same rule. The behavior of each pending action is in Pending confirmations. Exit codes of `pending`: 0, 2.

### cron

`cron install|uninstall` writes or removes a managed crontab block (design guide §4.3): first line `# ticket-work managed`, last line `# ticket-work managed end`, an explicit `PATH`, the `XDG_CONFIG_HOME` and `XDG_STATE_HOME` lines when set, and the optional user-owned env-file prefix. It installs `ticket-work sync --quiet --actor auto:cron` every `--sync-interval` (default `10m`). With `--with-start` it also installs `ticket-work start --auto --quiet --actor auto:cron` every `--start-interval` (default `30m`); starting automatically is opt-in. `--sync-interval` and `--start-interval` accept only ticket-queue's closed set (`1m 2m 3m 4m 5m 6m 10m 12m 15m 20m 30m 1h 2h 3h 4h 6h 8h 12h 24h`); `cron install` rejects `%`, newline and whitespace in every value it writes (cron treats `%` as a newline). An end-less block is never replaced. Exit codes: 0, 2.

### export, prune and validate

`export` prints audit records as JSON lines (`--since`, `--after-seq`, `--to PATH`, as ticketctl); there is no log export. Exit codes 0, 2.

`prune` deletes finished work items (phase `merged`, `stopped` or `failed`) older than `retention.work` (default 90 days) with their links and resolved pending records, and expired pending records older than `retention.pending`; it never touches `audit.jsonl`. It skips a finished item whose `cleanup.teardown` is `pending` or `refused` or whose `cleanup.claim` is `held`, prints a warning `agent_left` (agent ids) for every deleted item whose stored agent is not torn down, and deletes prompt files older than a day. Exit codes 0, 2.

`validate` checks the config and the sibling tools: each required tool is installed and at its minimum version, `ticketctl whoami` works per configured site, every board has a `started.to`, a `started.from`, repository rules and a resolvable repository (`wtctl locate`), `<state dir>/jobs` exists or can be created (mode 0700), the work-id and site name limits hold, there is one board per site, `queue_board` is set where used, and names present in both `jobs.pass_env` and `agent.env_allowlist` are reported as notices. It runs `ticket-queue validate` and reports its problems as `warnings` (a failure unrelated to ticket-work's use does not fail `validate`). `--probe` also runs `forgectl whoami --host` for each host of a mapped repository. Exit codes 0 or 12 (problems listed in `details.problems`).

## Work item and phases

A work item's `phase` is derived at each `sync` from the other tools' facts and set by the commands; the store caches it for `list` and `show`.

| Phase | Meaning |
|---|---|
| `pending` | a pending start exists and nothing was applied to the ticket (a human or a hook still has to answer) |
| `applying` | the confirmed start is being applied to the ticket; `previous`, the plan hashes and the step list are stored; no job exists yet |
| `starting` | the start changes were applied (or there were none), the job exists or is being added, and the agent has not started a run |
| `working` | an agent exists and no counting linked pull request is open |
| `in_review` | at least one counting linked pull request is open (draft or ready) |
| `merged` | the `pr_merged` condition holds (the rule's own outcome is tracked by its event); cleanup progress is `cleanup` |
| `stopped` | `stop` ran |
| `failed` | the start was restored or rejected, expired or abandoned before any agent run (a launch failure, a vetoed or canceled job, a rejected or expired pending start) |

`needs_attention` is true while the item has at least one attention reason; `attention` is the list of `{reason, detail, since}` (one entry per reason, ordered by `since`); `detail` is a small closed object per reason (host text untrusted and sanitized). Several reasons may hold at once, and an item with an attention keeps its phase.

`cleanup` has `teardown` (`not_needed`, `pending`, `done`, `refused`) and `claim` (`held`, `released`).

### Attention reasons

| Reason | Set when | Cleared when |
|---|---|---|
| `restore_failed` | the restore flow could not undo a step | the item is restarted or re-adopted, or stopped |
| `pr_idle` | no activity on any open counting pull request for `sync.pr_idle_after` | activity is newer or no open counting pull request |
| `pr_closed_unmerged` | every counting linked pull request is closed and none merged | a counting pull request is open or merged again, or the item is stopped |
| `superseded` | a newer counting pull request replaces an older open or closed one (Stale and diverged work) | the pair no longer exists |
| `ticket_diverged` | the claim state shows someone else changed the ticket (Stale and diverged work), or a renewal was refused with `gone` or `hidden` | the item is stopped |
| `candidate_link` | a `candidate` link exists | no candidate remains (linked or ignored) |
| `teardown_refused` | teardown was refused (Teardown) | teardown is `done` |
| `agent_blocked` | the agent's attention is `blocked` or `escalated` | the agent is live again or its last outcome is `done` |
| `agent_failed` | the agent's attention is `failed`, `timeout`, `lost` or `unreported`, or its artifact is invalid, or no pull request exists after `done` | a later run is live or `done` with a valid artifact |
| `job_held` | a held job with no agent report (launch escalation, manual hold) | the job is not held |
| `job_failed` | a terminal failed or canceled job while an agent ran, or a veto of a resume | a new job is added (`resume`) or the item is stopped |
| `pending_expired` | a pending start expired | the item is restarted |
| `sync_failed` | a step failed for the item | the next `sync` handles the item without error |
| `sprint_failed` | the sprint write failed after the transition landed | the item reaches `merged` or is stopped |
| `claim_lost` | a lapsed claim could not be re-taken (Sync order, step Claims) | the claim is held again |
| `agent_missing` | a stored agent id gives exit 10, or adoption found several candidates | an agent is adopted or found |
| `rule_failed` | a status-map rule failed permanently (Events) | the event is re-evaluated and applied, declined or skipped |

Every reason added to the set fires `post-attention` once for that addition (a reason cleared and set again fires again); a reason that changes only its detail does not. The payload carries `reason` and `dedupe_key` (`<work id>:<reason>`).

## Start order

0. **Lookup and lease.** Resolve `KEY`: a `site:KEY` argument names the site; a bare key is resolved through ticketctl's own site selection (`ticketctl get KEY`); an ambiguity exits 21 (`ambiguous_key`, `details.candidates`); a site no board uses exits 20 `unmapped` (`details.why: no_board`). Look up the work item in the store (no lower tool). A work item in phase `pending`, `applying`, `starting`, `working`, `in_review` or `merged` exits 20 `already_started` (`details.phase`; the hint is `resume`) before any claim is made. A `stopped` item takes the re-adopt path and a `failed` item the restart path (Re-adopt and restart). Then take the ticket lease (Concurrency).
1. **Gate (`--auto` only).** `start --auto` requires jobsctl (`jobs.enabled: true`); otherwise it exits 2 `invalid_combination`. `capacity` is `effective_free` of `jobsctl capacity --queue <jobs.queue> --json`; `null` means unbounded. The count `pending_starts` is the number of open pending records of action `start`. If `capacity` is not `null` and `capacity - pending_starts <= 0` the command exits 22 `nothing_to_start` (`reason: no_capacity`); if `pending_starts >= start.max_pending` it exits 22 (`reason: pending_exists`). A human `start` has no gate; when `effective_free` is 0 or less the dialog shows "the job will wait in the queue" and the result carries the warning `queue_full`.
2. **Claim.** `start KEY`: `ticket-queue claim KEY --holder <holder> --label store=<store id> [--ttl D]`; `start`: `ticket-queue next --claim --holder <holder> --label store=<store id> [--board <queue_board>] [--ttl D]`. A refusal (exit 20) is passed through (`reason` and `details.lower_error` from ticket-queue); exit 22 from `next` is `nothing_to_start` (`reason: empty`). A claim is local: it writes nothing to the ticket system. A result with `renewed: true` for a ticket with no work item is an orphan claim of this store and is used as it is.
3. **Read.** `ticketctl get KEY --fields key,status,type,labels,assignee,reporter,estimate,blocked,parent,epic,sprint,title` live (the fields the preconditions, the plan and the dialog read; the prompt reads its own fields at launch, Slot contract). A key that moved is followed (the work item takes the canonical key and keeps the requested key in `requested_keys`).
4. **Resolve.** The board is the one board whose `site` equals the ticket's site. The repository and base come from the ordered rules (Ticket to repository and branch); a ticket matching no rule exits 20 `unmapped` (`details.why: no_rule`). `wtctl locate <repo-id> --json` is run for the repository (wtctl may auto-clone when its own `auto_clone` is on; that is wtctl's configured behavior and also applies to `--dry-run`); a repository wtctl cannot resolve exits 12 `repo_unresolved` before anything is changed (wtctl exits 10, 12, 20 and 21 all map to `repo_unresolved`, with `details.lower_error`).
5. **Preconditions and trust.** Every rule of the board's `preconditions` is evaluated against the live ticket (Preconditions). A failure exits 20 `precondition_failed` (`details.rules`, `details.unknown` for values ticketctl reported as unknown). `status_in` is redundant with `started.from` (step 7); a board may use both. A ticket whose prompt would exceed 1 MiB (title, description, acceptance criteria and the other fenced fields, comments excluded) is refused before any write with exit 20 `precondition_failed` and `details.rules: ["prompt_too_large"]`. An unattended start (Unattended runs) whose ticket `reporter` is neither the user's own account nor in `boards.<name>.trusted_authors` exits 20 `untrusted_reporter` (`details.reporter`).
6. **`pre-enqueue` hooks.** Payload `phase` is `null` and `object_id` is the work id `site:KEY` when no work item exists yet. A veto exits 11 and an escalation records a pending start (exit 13).
7. **Plan.** `ticketctl transition KEY --to <started.to> [--assign me] --if-status <live status> --dry-run` (`--assign me` only when the rule has `assign: me`; `--resolution` only for a done target), then `ticketctl sprint add KEY --sprint <started.sprint> --dry-run` when the rule names a sprint. The live status must be one of `started.from`, else exit 20 `precondition_failed` (`details.rules: ["started.from"]`, `details.current_status`). `previous` (status, assignee, sprint ids) and the planned `changes` are taken from the dry-run output; nothing is stored yet.
8. **Confirm.** The Confirmation matrix. A decline exits 20 `declined`, stores nothing and releases the claim plainly.
9. **Record intent (write-ahead).** Before the first write the work item is stored (or updated from `pending`) with phase `applying`, `previous`, `started_status`, the plan hashes, the run token and the settings snapshot (Job command), and the step list: one entry per planned write (`transition`, `sprint_add`), each `planned`. After each write returns, its status (`applied`, `unchanged`, `skipped`, `failed`, `unknown`) is stored in the same transaction as the result.
10. **Apply.** For each write the `pre-transition` hooks run first (hook outcomes below), then `ticketctl ... --yes --expect-plan <hash> --actor <actor> [--decision-id ...]`. The result is handled by the table Apply outcomes.
11. **Enqueue.** The work item moves to `starting`, the event `started` is recorded (Events) and the job is added: `jobsctl add --queue <jobs.queue> --unique-key ticket:<site>:<KEY> --max-retries 0 --timeout none --cwd <state dir>/jobs --kill-grace <jobs.kill_grace> --label ticket=<KEY> --label owner=ticket-work --pass-env <name>... --actor <actor> -- <executable> [--config <path>] _job <work id>`. `<executable>` is the real path of the running ticket-work executable. The directory `<state dir>/jobs` is created (mode 0700) by ticket-work before the first add. A result with `created: false` (an existing non-terminal job of the key) stores that job's id and adds the warning `existing_job`. A `pass_env_undefined` warning cancels the job and runs the restore flow. Without jobsctl the job command runs in the foreground of `start`: a human `start` then exits with the job's exit code mapped by the Job command table (0 when the agent reported done, 13 blocked, 14 to 18 passed through) and prints the start result with `job: {id: null, foreground: true, exit_code}`. `start --auto` never runs without jobsctl, so cron never blocks for an agent's lifetime. `resume` without jobsctl behaves the same.
12. **Output.** The start result object. Exit 0.

A `--dry-run` start performs steps 0 to 5 and 7, reads and dry-runs only, stores nothing, claims nothing (it uses `ticket-queue claim --dry-run` or `next --claim --dry-run`) and takes no lease.

### Apply outcomes

| Result | First write (the transition, with its assignment) | Later write (`sprint add`) |
|---|---|---|
| exit 0 (`applied` or `unchanged`) | step recorded, continue | step recorded, continue |
| exit 20 `stale_ticket` | re-plan once (step 7). A human at a TTY is asked again; otherwise nothing landed, the claim is released per Claim release rules and the start exits 20 | the same re-plan; if it fails again `sprint_failed` |
| exit 12 `outcome_unknown` | step `unknown`; re-run the same command once with the same `--expect-plan` (a landed write is `unchanged`); still unknown: restore flow with a live read first, exit 12 | step `unknown`; re-run once; still unknown: `sprint_failed` |
| exit 12 `partial` | record the sub-steps from `details.result.steps[]`; restore flow, exit 12 | not applicable |
| exit 13 `escalated` (ticketctl's own hook) | nothing landed: pending start (`escalated_by: ticketctl`), exit 13, claim held; ticket-work never passes `--override-escalation` | `sprint_failed` (detail `escalated`) |
| exit 20 other (`no_such_transition`, `sprint_closed`, `precondition_failed` from `--if-status`) | nothing landed: release per Claim release rules, exit 20 with the lower reason | `sprint_failed` (detail the lower reason) |
| exit 21, 22, or 12 other | nothing landed: exit 12 `lower_failed`, release per Claim release rules | `sprint_failed` |
| any failure after a first write landed that is not a sprint failure (a later `update`, a crash, `outcome_unknown` unresolved) | restore flow (Restore) and release with `--failed` | not applicable |

Hook outcomes for `pre-transition` during `start`: a veto before the first write exits 11, nothing landed, release per Claim release rules; an escalation before the first write records a pending start (`escalated_by: <hook>`) and exits 13; a veto or escalation before a later write is `sprint_failed` (detail `vetoed` or `escalated`). In `sync` (a status-map rule): a veto records the event `skipped` (reason `vetoed`, re-evaluated per Events); an escalation records a pending confirmation (`escalated_by` the hook). In `confirm`: a veto exits 11 and an escalation exits 13 with the record left open.

### Confirmation matrix

| Situation | Result |
|---|---|
| human actor, TTY, no `--yes` (a `confirm: ask` rule) | the dialog reads `/dev/tty`; it shows the key, the sanitized title, the reporter's display name, the repository, branch, base, mode, sandbox, setting sources, the queue warning when the queue is full, and both plans (status, assignee, sprint changes by name); one question; a no is `declined` |
| human actor, `--yes` (any TTY state) | the caller confirmed in its own dialog; no prompt; the plans are applied (steps 9 and 10) |
| no TTY, no `--yes`, any actor | a pending record is created (`action: start`, `details.changes`), `post-pending` fires, exit 13, the claim stays held |
| `auto:` actor | never prompts; `--yes` exits 2 `human_only`; the result is as for no TTY |
| rule `confirm: auto` | applied without asking, any actor, including `start --auto` and `sync` |
| rule `confirm: never` | the rule is not applied |
| a `pre-transition` hook whose stdout JSON has `"enforced": true` and `"decision": "allow"` (design guide §12) | a `confirm: ask` write is applied without asking; exit 0 without that JSON means only "do not block" |

### Claim release rules

| Outcome | Release |
|---|---|
| a refusal or lower failure of a human `start KEY` before step 10; a decline; a hook veto; a rejected or expired pending start; a diverged ticket | plain `release` (`ticket-queue release KEY --holder <holder>`) |
| `start --auto`: any refusal or lower failure after its claim and before step 10 (`precondition_failed`, `unmapped`, `untrusted_reporter`, `already_started` for a `stopped` item, `repo_unresolved`, a veto, any exit 12) | `release --failed`, so ticket-queue's auto-skip removes a ticket after `claim.max_failures` tries |
| a failure after a write landed (the restore flow) | `release --failed`, except plain when the lower error has `details.retryable: true` or a human canceled the job |
| a refusal for an item that exists in an active phase | no claim was made (step 0 refuses first) |

A refusal releases only the claim of this call or an orphan claim of this store (`renewed: true` with no work item); it never releases a claim of an active work item.

### Re-adopt and restart

A `stopped` item is re-adopted by a human `start KEY` (never by `start --auto`, which refuses it as `already_started` and releases with `--failed`). Re-adopt claims the ticket again (steps 2 and 3), evaluates only `not_blocked` and `labels_absent` and requires the live assignee to be `me` or empty; it skips `started.from`, every other precondition, the plan and the apply (the ticket is not changed, `previous` is kept, the event `started` does not fire again), clears the attention reasons that stop clears, and moves the item to `working` when an agent id is stored (else to `starting`) and enqueues a job whose command resumes the agent.

A `failed` item is restarted by the full flow (steps 2 to 12); `previous` and `restore_state` are reset, a stored parked agent that never ran is kept and the job command resumes it instead of launching a second one (Job command).

## Job command

`ticket-work _job WORK_ID` is what the jobsctl job runs; its output is not a contract. It is resume-aware: it reads `JOBSCTL_JOB_ID` and `JOBSCTL_ATTEMPT` but decides from its own records. The work item stores at Start order step 9 a `settings` snapshot: the resolved `mode`, `skill`, `sandbox`, `permission_profile`, `setting_sources`, `env_allowlist`, `plugin_dirs`, `model`, `timeout`, `unattended`, the `actor`, the `decision_ids` and the run token. `_job` uses the snapshot for every agent call and for the actor of every write and audit record of the job; all other configuration is read from the config files at run time (`--config PATH` is forwarded in the job argv when the start used it; `TICKET_WORK_*` variables are not inherited by jobs, which is why only non-safety scalars can be set from the environment). `jobs.pass_env` names are available to the job for ticket-work's own tool calls only. `_job` takes the ticket lease only for its short sections (loading the item, storing the agent id and the result, the restore flow).

1. Load the work item. Refuse (exit 20 `not_current_job`) when `JOBSCTL_JOB_ID` is set and differs from the stored job id, and refuse (exit 20 `not_active`) when the phase is not `starting`, `working` or `in_review`.
2. Run the `pre-launch` hooks. A veto restores the start (when the agent never ran) and exits 11. An escalation records the attention `job_held` (detail `launch_escalated`), a pending confirmation of action `launch`, and exits 13 (the job is held with reason `exit_13`).
3. Find the agent: the stored id is checked with `agent-spawn show`; otherwise Agent adoption.
4. Launch. Without a parked agent: first `agent-spawn launch --dry-run --json` with the same flags; it must exit 0 with `agent_settings.kind == "implement"`, `reads_third_party == false`, `would_refuse == null` and an empty `warnings` (otherwise exit 12 `lower_failed` with `details.cause: kind_check`, restore flow). Then `agent-spawn launch --kind implement --mode <mode> --repo <repo> --branch <branch> --base <base> --worktree new --skill <skill> --plugin-dir <bundled plugin> [--plugin-dir <configured>...] --prompt-file <file> [--input-file <file>] --permission-profile <profile> --sandbox <level> --setting-sources <list> --env-allowlist-only <name>... [--model <m>] [--timeout <d>] --label ticket=<KEY> --label owner=ticket-work --label repo=<repo> --wait --result-file <file> --json`. A stored agent that is parked and never ran (status `launch_failed`, no run) is continued with `agent-spawn resume <agent_id> --mode <mode> --prompt-file <file> --wait ...` (agent-spawn re-runs the launch for an agent without a session). A parked agent that ran: `agent-spawn resume <agent_id> --mode <mode> [--prompt-file <file>] --wait --result-file <file> --json`. A live agent: `agent-spawn wait <agent_id>` (no signal is forwarded; `jobsctl cancel --force` reaches only an agent started by this job's launch). The prompt file is built here, at each launch or resume (Slot contract). Every `launch` and `resume` call carries `--timeout <agent.timeout>` when `agent.timeout` is set (default none: a headless implement run is then bounded by claude-session's own kind default, 60 minutes; set `agent.timeout` for longer runs), `--model <agent.model>` when set, and `--setting-sources` as the comma-joined list (an empty list is `""`); `jobsctl add` carries `--timeout none` so a queue timeout never kills an agent.
5. Classify by the JSON root (`error` or `agent`), the `phase` and the exit code with the table below. The agent id from the result is stored at once; so are the report and the validated artifact fields (Slot contract).
6. Exit with the table's job exit.

| agent-spawn outcome | job exit | work item effect |
|---|---|---|
| exit 0, `done`, valid artifact | 0 | clear agent attention; phase from the next `sync` |
| exit 0, `done`, missing or invalid artifact (schema, ticket, `skill_marker`, `run_token`, `report.implicit: true`) | 18 | attention `agent_failed` (detail `artifact_invalid`), event `agent_failed` key `<agent id>:<run>`; no restore |
| exit 13, `report.status` blocked or needs-input | 13 | job held (`exit_13`); attention `agent_blocked`, event `agent_blocked`; `job_held` is not set for this pair |
| exit 13, launch escalated (`phase: launch`) | 13 | pending `launch` record, attention `job_held` (detail `launch_escalated`) |
| exit 11 (`vetoed` launch) | 11 | restore when the agent never ran; `post-start-failed` |
| exit 12 or an error envelope or `phase: launch` (no run started) | the lower exit (12 when none) | restore when the agent never ran; the claim is released plainly when `details.retryable` is true; the agent id is kept |
| exit 14 unreported, 16 timeout, 17 lost, 18 failed | the same | no restore; attention `agent_failed` (detail the outcome), event `agent_failed` (`killed` 15 sets no attention and no event) |
| exit 20 (`third_party_*`, `tearing_down`) | 20 | no restore; attention `job_failed` (detail the reason) |
| exit 130 or 143 | the same | agent parked; attention `job_failed` when the job ends non-canceled |

The job command never passes `--yes`, `--force` or `--override-escalation` to any tool. A `pre-launch` veto when an agent already exists (a resume) exits 11 with nothing restored; the item keeps its phase and gets the attention `job_failed` (detail `vetoed`); `resume` creates a new job.

Held jobs and `sync`: `job_held` is raised only for a held job that has no agent report (a `launch` escalation or a manual hold); a held `exit_13` job whose agent reported blocked or needs-input shows `agent_blocked` only; a held job whose agent has since started again (a human resumed it with agent-spawn) is resolved with `jobsctl resolve <id> --as done`; the agent then runs outside any job and its slot is no longer counted, which is accepted and recorded in Residual risks.

## Agent adoption

A work item without a stored agent id adopts one with this procedure, run by `_job` (step 3), by `sync` (step Agents), by `stop` and by `resume`. For each key in `key` and `requested_keys`: `agent-spawn list --label ticket=<KEY> --label owner=ticket-work --json`; with a stored job id also `--label job=<job id>` is tried first (agent-spawn adds `job=` from `JOBSCTL_JOB_ID`; a foreground run has no such label). A candidate is accepted only when its `kind` is `implement`, its `repo` equals the work item's repository, its `created` is not earlier than the work item's `applying` time, and the worktree record named by its `worktree.record_id` (`wtctl show <record_id> --json`) has `branch` equal to the recorded branch. Exactly one accepted candidate is adopted: its id is stored on the work item. Several accepted candidates: none is adopted and the attention `agent_missing` is set with detail `ambiguous`. When wtctl cannot be read, no candidate is accepted (the next `sync` retries). A stored id is never replaced by a label match. Labels only find candidates; stop, teardown, events and the restore act only on the stored id.

## Sync order

1. **Lease.** Take the sync lease; a held lease sets `sync_rerun` and exits 0 `already_running` (Concurrency). A run that ends with `sync_rerun` set runs steps 2 to 12 once more.
2. **Expiry.** An open pending record past its expiry becomes `expired` (audit `pending_expire`). An expired `start` pending releases the claim plainly, sets the item to phase `failed` (`restore_state: done`) and sets the attention `pending_expired`; an expired `launch` pending cancels its job and restores when the agent never ran (Restore); an expired `transition`, `comment` or `stop` pending only drops the record (the next `sync` creates it again while the event still holds). Prompt files older than one day are deleted.
3. **Repair.** A work item in phase `applying`, or in phase `starting` with no stored job id for which `jobsctl show --unique-key ticket:<site>:<KEY>` finds no job, whose ticket lease is not held and whose `updated` is older than `claim.orphan_after`, runs the restore flow using the stored step statuses: only steps with status `applied`, or `unknown` that a live read shows landed, are undone. A job found by unique key is adopted (its id stored) and the item continues as `starting`.
4. **Claims.** `ticket-queue claims --holder <holder> --json` gives each claim's `ticket_state`. Claims of work items in phase `pending`, `starting`, `working` or `in_review`, and of items whose `cleanup.claim` is `held` (phase `merged` while cleanup is outstanding), are renewed (`claim KEY --renew --holder <holder>`) when the remaining life is below `claim.renew_below` of the TTL; a claim state `moved` is renewed with the canonical key and the item updated. A refusal `not_held` (the claim lapsed) first tries `ticket-queue claim KEY --holder <holder> --label store=<store id>` (a new claim); only when that is refused (`claimed` by another holder, `done`, `gone`, `skipped`, `hidden`) is the attention `claim_lost` set (detail the lower reason); a re-held claim clears `claim_lost`. A renewal refused with `gone` or `hidden` sets `ticket_diverged` (detail the reason). Entries with `hidden: true` carry no `ticket_state` and are renewed like any other. The claim states `done`, `gone` and `reassigned` are evaluated for items in the active phases only (Stale and diverged work). A claim of this store (label `store=<store id>`) with no work item, older than `claim.orphan_after` (default 15 minutes), whose ticket lease is not held, is released plainly.
5. **Agents.** For every active work item without a stored agent id run Agent adoption. `agent-spawn list --label owner=ticket-work --json` plus `agent-spawn show` for every stored id updates each item's agent facts (status, `needs_attention`, last outcome); a stored id that gives exit 10 sets the attention `agent_missing`. Agent attention `blocked` or `escalated` raises the event `agent_blocked`, and `failed`, `timeout`, `lost` or `unreported` raise `agent_failed`.
6. **Jobs.** For an item with a stored job id: `jobsctl show <job id> --json` (an item in `starting` without an id adopts the job found by `jobsctl show --unique-key ticket:<site>:<KEY>`). A canceled, vetoed or failed job restores the start only when the agent never ran (Restore); with an agent that ran it sets the attention `job_failed`. Held jobs: Job command.
7. **Discovery.** Discovery and read, below.
8. **Read.** Discovery and read, below.
9. **Stale flags.** `pr_idle`, `superseded`, `pr_closed_unmerged` and `ticket_diverged` handling (Stale and diverged work).
10. **Rules.** Each event that is new or due for re-evaluation (Events) is evaluated against the board's status map: applied, recorded as a pending confirmation, or skipped.
11. **Cleanup.** After `pr_merged`: teardown (Teardown), then release the claim plainly.
12. **Attention and hooks.** Attention reasons are set and cleared by the Attention reasons table; hooks are fired and the outbox is delivered (Hooks).

Each step records its own failure per work item (attention `sync_failed` with the step and lower code) and continues with the other items; a failure of a lower tool for the whole run exits 12 `lower_failed`, a failure for part of it exits 12 `partial_results`.

### Discovery and read

**Discovery.** The repositories discovered are those named by a rule of every board that has a work item in an active phase. For each: `forgectl --json prs --repo <repo id> --author me --state all --updated-since <cursor minus sync.overlap> --limit 1000`. When a board names more than 5 repositories on one host, one host-wide call (`--host <h> --author me`) replaces the per-repository calls and its items are filtered to the mapped repositories. The cursor is the newest `updated_at` seen per repository; a repository with no cursor starts at the oldest `created` among the active items of its boards. Only a full `sync` stores cursors. A result with `complete: false` is re-run once split by `--state` (open, closed, merged); if one is still incomplete the item gets `sync_failed` (detail `incomplete`). An empty list is never evidence that a pull request is absent (PR linking).

**Read.** `forgectl --json show <pr>` for every linked, non-ignored pull request whose list item changed, and for every open one at least every `sync.reread_open_after` (default one hour). `show` takes the stored display `pr`; exit 10 marks the link `missing` and, in the same run, triggers one host-wide `prs --author me --host <h> --updated-since <cursor minus overlap>` whose items are matched by `repo_id`/`pr_id`: a pull request found under the same `pr_id` with another `repo` (a rename or a move) updates the stored `pr` and `repo` and restores the link. Facts are compared with the stored facts to derive events.

**Authorship.** Membership in a `--author me` listing never proves authorship: every link is verified by `show`, and the author is compared with the login that `forgectl whoami --host <h>` returns for the pull request's host (called once per host per run, cached for the run). A host whose login cannot be resolved makes the pull request not linkable (`why: author_unknown`) and `validate --probe` reports it.

**Idle signal.** Link facts are `state`, `draft`, `head_sha`, `head_ref`, `base_ref`, `is_fork`, `merged_head_sha`, `updated_at` and `activity_at`. `activity_at` is `updated_at` unless it is older than `sync.pr_idle_after`; then (for open counting pull requests only) one `forgectl --json snapshot <pr> --no-bodies` per run supplies the newest CI or review time and `activity_at` is the newer of the two (minimum forgectl version 0.52.0 covers `snapshot --no-bodies`).

## Status map

The map is per board, keyed by event name. Every event may have one rule; an event without a rule fires its hooks and does nothing else.

### Events

| Event | Fires when | Event key |
|---|---|---|
| `started` | the start changes were applied (or there were none), once per work item | `once` |
| `pr_opened` | a counting linked pull request is first observed, in any state, once per work item | `once` |
| `pr_ready` | a counting linked pull request is first observed not a draft (open or merged), once per work item | `once` |
| `pr_merged` | at least one counting pull request merged, none counting is open, and the agent condition holds | first 16 hex of sha256 of the sorted merged `pr_id` values joined by `,` |
| `pr_closed_unmerged` | every counting linked pull request is closed and none merged | the same hash over the sorted `pr_id` set |
| `agent_blocked` | the agent's attention is `blocked` or `escalated` | `<agent id>:<run>` |
| `agent_failed` | the agent's attention is `failed`, `timeout`, `lost` or `unreported`, or its artifact is invalid | `<agent id>:<run>` |
| `stopped` | `stop` ran | `once` |

`pr_merged` requires also that the agent condition holds: no agent is stored, the agent is torn down, or the agent is not live, its last outcome is `done` with a valid stored artifact, and every pull request url in `last_artifact.prs` is linked and not open (or `ignored`). When a counting pull request merged and none is open but the agent condition does not hold, `post-status` fires with `event: pr_merged_partial` (reason `agent_unfinished`) and no rule applies. A merge while other counting pull requests are open fires `post-status` with `event: pr_merged_partial` (reason `others_open`) and applies no rule. Phase `merged` is the state in which the `pr_merged` condition holds, whatever the outcome of its rule.

An event is identified by `(work id, event, event key)`. The pull request events due in one evaluation are applied in the order `pr_opened`, `pr_ready`, then `pr_merged` or `pr_closed_unmerged`; only the latest due one is applied and the earlier ones are recorded `skipped` with reason `caught_up` (so a pull request that was opened and merged between two syncs moves the ticket once). A phase `merged` item evaluates no further pull request events. Outcomes: `applied` (ticketctl applied or answered `unchanged`), `pending`, `declined` (a rejected pending record), `skipped` (reason `no_rule`, `never`, `caught_up`, `from_mismatch`, `vetoed`, `item_diverged`) and `failed`. `applied`, `declined` and `skipped` with reason `no_rule`, `never`, `caught_up` or `item_diverged` are final. `skipped` with reason `from_mismatch` or `vetoed`, and `failed`, are re-evaluated only when the rule text changed (a stored rule hash) or the live ticket status differs from the status seen at the last evaluation (`seen_status`); `post-status` fires for such a re-evaluation only when the outcome changed. An open `pending` record is final for its event while it is open; an expired one drops the record and the next `sync` creates it again. A rejected one marks the key `declined`.

A rule failure is permanent when ticketctl answers exit 20 (`no_such_transition`, `sprint_closed`), 21, 22 or exit 12 `rejected` (including `needs_assignee`) or `lookup_incomplete` for a comment: the outcome is `failed`, the attention `rule_failed` is set with detail `{event, lower_code, reason_hint}` and the rule is not retried until it changed. Every other lower failure is transient: the item gets `sync_failed` and the event is evaluated again at the next `sync`.

### Rule fields

| Field | Meaning |
|---|---|
| `to` | target status name (required; ticketctl chooses the transition by target) |
| `from` | list of status names the ticket must be in; required for `started`; for other events absent means no guard. The live status is checked by ticket-work and passed to ticketctl as `--if-status <live status>` |
| `resolution` | required when the target is a done status. ticket-work cannot know status categories at load, so a missing resolution is found by the plan (ticketctl exit 22 `missing_required_fields` or `invalid_value`) and is a permanent failure (Events) |
| `assign` | `me` only (any rule): assigns when the ticket is unassigned (ticketctl `--assign me`; an assigned ticket gives the plan warning `assign_skipped`, which is recorded and is not an error); `none` and account ids are a config error (`invalid_config`) |
| `sprint` | `open`, `next` or a numeric sprint id (`started` only) |
| `confirm` | `ask` (default), `auto` or `never` (Confirmation matrix) |
| `comment` | `true` posts one fixed-text comment per event (Ticket comments) |

`confirm: auto` applies without asking; it is set only in config files, never by a flag or an environment variable, per board and event, and `defaults.confirm` sets the default for rules that give none. `confirm: never` turns the rule off. Each applied rule writes the transition through ticketctl (plan with `--dry-run`, `--yes --expect-plan <hash>` after the confirmation, `--actor`, `--decision-id`) and an audit record.

A board without `started.to` or `started.from` refuses `start` and fails `validate`. ticket-work ships no status names; `config.example.yaml` documents the shape with placeholder names.

### Ticket comments

`comment: true` on a rule (or `link_comment: true` on a board, which applies to the event `pr_opened` evaluated at `sync`; `ticket-work link` never posts a comment itself) posts one comment through `ticketctl comment KEY --body-file <file> --dedupe-key <key> --yes --expect-plan <hash>`. The dedupe key is `ticket-work:` followed by the first 32 hex characters of sha256 of `<site>:<KEY>:<event>:<event key>`; this matches ticketctl's grammar and is at most 44 characters. The body is fixed text built from trusted data only (the event name and the pull request URL), followed by ticketctl's attribution paragraph for automatic actors. It follows the rule's `confirm` flow like a transition. After `outcome_unknown` it is retried with the same key; `lookup_incomplete` (only a human may post without a key) is a permanent failure. Comments are off by default.

## Stale and diverged work

- `pr_idle`: no activity on any open counting linked pull request for `sync.pr_idle_after` (default 14 days); activity is `activity_at` (Discovery and read). Cleared when activity is newer or no counting pull request is open.
- `pr_closed_unmerged`: every counting linked pull request is closed and none merged. The default is to notify only: the event has no rule, `post-status` fires with outcome `skipped` (reason `no_rule`) and the attention `pr_closed_unmerged` is set; no transition and no teardown.
- `superseded`: a counting linked pull request exists that has the same repository and the same `base_ref` as an older counting pull request of the work item that is open or closed unmerged. Stacked pull requests (different base chain) and pull requests of different repositories never match. Cleared when no such pair exists.
- `ticket_diverged`: someone else changed the ticket. Evaluated only for work items in phase `pending`, `starting`, `working` or `in_review`. It is set when the claim state is `gone` or `reassigned`, or `done` while the item has no counting merged pull request. `assign` is restricted to `me`, so `reassigned` always means a human took the ticket. The only automatic actions are releasing the claim plainly and applying no ticket write rule to the item from then on (outcome `skipped`, reason `item_diverged`); `sync` keeps reading pull request facts, raises hooks, and tears down after a merge. A `moved` claim is renewed with the new key. A claim state `done` with a counting merged pull request is the normal path to cleanup, not divergence. Items in `merged`, `stopped` and `failed` are never diverged.

Staleness never transitions a ticket, never tears down a worktree and never closes a pull request.

## Preconditions

`boards.<name>.preconditions` is a list of named checks from a closed set; each entry is `{name, check, ...}` (`name` matches `^[A-Za-z0-9._-]{1,128}$` and appears in refusals). List checks take `values`, scalar checks take `value`; `has_estimate`, `not_blocked` and `has_parent` take none.

| Check | Passes when |
|---|---|
| `has_estimate` | `estimate` is a number; `null` with `incomplete: ["estimate"]` fails as unknown |
| `status_in` (`values`) | the live status name is in the list (case-insensitive); redundant with `started.from`, a board may use both |
| `assignee` (`value`: `me`, `none`, `any`) | the ticket's assignee matches (`me` is the account id from `ticketctl whoami`) |
| `not_blocked` | `blocked.value` is `false`; `null` fails as unknown |
| `has_parent` | the ticket has a `parent` |
| `in_sprint` (`value`: `open`, `any`) | the ticket is in an active sprint (`open`) or any sprint |
| `labels_absent` (`values`) | none of the labels is present |

Preconditions run at `start` (step 5) and again at `confirm` of a pending start. A value ticketctl reports as unknown fails the check and the refusal says it was unknown. Organization logic that does not fit the set belongs in a `pre-enqueue` hook.

## Ticket to repository and branch

- **Boards.** A site has exactly one board: a configuration with two boards naming the same `site` is refused at load (exit 2 `invalid_config`). `boards.<name>.queue_board` (optional) is the ticket-queue board whose tickets this board takes. `--board B` on `start` and `list` always names a ticket-work board.
- **Rules.** `boards.<name>.repos` is an ordered list of rules `{match: {label, project, epic, issue_type}, repo: <repo id>, base: <branch>}`; the first match wins and a rule with an empty `match` is the board default. `match` keys are all optional and ANDed, each a single string: `label` (equals one of the ticket's labels, case-insensitive), `project` (the key prefix before the first `-`, case-insensitive), `epic` (the epic's key, exact), `issue_type` (`type.name`, case-insensitive). `component` is not a match key (ticketctl has no component property). A ticket that matches nothing is refused with `unmapped`. A `repos.<id>` override entry (per-repository settings) takes the per-repository position in the precedence order.
- **Branch.** The branch is `<type>/<KEY>-<slug>`. `type` comes from `boards.<name>.branch.types` by issue type (default `feat`). The slug is derived from the title by one rule: NFKD-normalized, ASCII only, lower-case; runs of characters outside `a-z0-9` become one `-`; the result is split on `-`; every all-digit token is dropped together with the token before it; the tokens are joined with `-`; the result is cut to 40 characters, then trimmed of `-`; `ticket` when empty. No other ticket text reaches the branch and no other ticket's key can appear in it. Examples: `Follow up to PROJ-1 regression` gives `follow-up-to-regression`; `Fix PROJ-10 and PROJ-1` gives `fix-and`; a full-width `ＰＲＯＪ－１ fullwidth key` gives `fullwidth-key`. ticket-work passes `--branch` and `--base` to agent-spawn. The key always appears as a whole token behind `<type>/`.

## PR linking

Every link has a `tier`; linking never relies on the agent's claim alone.

A linked pull request **counts** (for the events, `pr_idle`, `superseded` and the teardown selection) when it is not from a fork (`is_fork` false) and its base chain ends at the work item's `base`: its `base_ref` equals the recorded `base`, or equals the `head_ref` of another counting linked pull request of the work item (checked iteratively). Pull requests linked by the manual tier count regardless of the chain. A linked pull request that does not count is shown (`counts: false`) and drives nothing.

| Tier | Evidence | Effect |
|---|---|---|
| `claimed` | the agent's artifact `prs[].url` (or a `pr=` label) names a pull request that forgectl `show` confirms: authored by the user's account, in a repository the board maps, with the head branch ticket-work launched (exact `head.ref` equality with the recorded branch), `is_fork` false, and the base chain of the counting rule | linked automatically |
| `branch` | `head.ref` equals the recorded branch of a work item (exact, checked first, the pull request belongs to that work item only), or contains the whole-token key of exactly one active work item (case-insensitive, any key of the item's `key` and `requested_keys`, never a generic pattern) for a pull request authored by the user in a repository the board maps, not a fork, whose base chain ends at the work item's base. A token that matches the keys of two or more active work items makes the pull request a `candidate` for none of them linked automatically (state `candidate`, attention `candidate_link` on each) | linked automatically |
| `title` | the key only in the title | recorded as `candidate`; fires `post-attention` (`candidate_link`); never moves the ticket until `link` |
| `manual` | `ticket-work link` | linked |

- The key matches `head.ref` with `(?<![A-Za-z0-9])KEY(?![A-Za-z0-9])` (case-insensitive, `KEY` escaped).
- Candidates are re-evaluated at every `sync` (a candidate becomes a link when the evidence becomes unambiguous, for example after the base chain resolves); `candidate_link` is set once per candidate `pr_id`.
- A link stores `pr_id` and `repo_id` (forgectl's opaque ids) and the display `pr` and `repo` (host/path) refreshed at every `show`; the board's repository rules are compared with the display `repo`, the stored `repo_id` follows a rename. A link also stores the tier, the time and the last-seen facts (`state`, `draft`, `head_sha`, `head_ref`, `base_ref`, `is_fork`, `merged_head_sha`, `updated_at`, `activity_at`).
- A link's `pr=` label (the pull request's forgectl `pr` field, not the user's typed form) is added to the work item's stored agent at link time (`agent-spawn label add <agent_id> pr=<pr>`); when no agent is stored or it is torn down (exit 10) the label is skipped (warning `label_skipped`) and `sync` adds it later when an agent exists (`label_synced` on the link). Labels are a multiset: adding the same pair is a no-op and nothing has to be replaced. ticket-work never reads labels; `pr=` exists for review-respond's lookup, which sees it only after the first `sync` that links the pull request (a bounded delay; the agent's own optional self-label closes it sooner).
- One ticket may have several links (stacked pull requests, follow-ups, one per repository).
- A pull request linked to one work item is never linked to another automatically (`linked_elsewhere`).
- `prs --repo` for a missing or renamed repository returns exit 0, an empty list and `complete: true`; `show` returns exit 10. An empty list is never read as "no pull requests": a link is marked `missing` only by a `show` exit 10.
- Discovery uses the cheap `prs` list; `merged_head_sha`, `merged_at` and `closed_at` need one `show`.

## Pending confirmations

A pending record has `id` (`^pd-[a-z2-7]{8}$`), `tool: ticket-work`, `action`, `target` (the work id), `created`, `summary`, `expires`, `actor`, `plan_sha256` (map of step to hash), `rule`, `event`, `escalated_by`, `status` (`open`, `confirmed`, `rejected`, `expired`) and `details`. `action` is `start`, `transition`, `comment`, `launch` or `stop`. Records never contain ticket text. `details.changes` is an array of `{step, field, from, to}` (status names, `me` or account ids, sprint ids; host text capped at 64 characters and sanitized); a `start` pending also holds `details.plans`. Expiry is performed by `sync` (Sync order step 2); `pending` also treats a record past its expiry as `expired` when it lists. A `confirm` after expiry exits 20 `expired` and does nothing else (the claim was already released by `sync` or is released by that `confirm` call when no `sync` ran). `declined` is the answer no at ticket-work's own dialog; it is never stored as pending.

- `start` pending: created by a non-TTY start, an escalated `pre-enqueue` hook or ticketctl's own escalation; the item phase is `pending`. It holds the claim (renewed by `sync`). `pending.start_expiry` defaults to 24 hours. `confirm` re-checks the claim live (a refused renewal tries a new `claim`; refused again is exit 20 `claim_lost`), re-evaluates the preconditions, re-runs the other `pre-` hooks (overriding only the escalating hook), re-plans with `--dry-run` and compares each step's hash with the stored `plan_sha256`; if any differs the old record becomes `rejected` (`details.superseded_by`), a new pending record is created and the command exits 13 (`stale_plan`); if the re-plan is empty (every step `unchanged`) the record is `confirmed` with nothing to apply; otherwise it continues at Start order step 9. `reject`, expiry and a diverged ticket release the claim plainly. A pending start that is rejected or expires sets the work item to phase `failed` with `restore_state: done` (nothing was applied) and releases the claim plainly; a later `start KEY` is then a restart.
- `transition` and `comment` pending: created by a non-TTY `sync` for a rule whose `confirm` is `ask`, keyed by work id, event and the event key so a repeated `sync` never duplicates it. `confirm` re-plans with `ticketctl ... --dry-run` and compares the hash as above (a stale plan supersedes the record, creates a new one and exits 13), then applies with `--yes --expect-plan <hash>`. Expires after `pending.expiry` (default 7 days); expiry drops the record only.
- `launch` pending: created when a `pre-launch` hook escalated in the job. `confirm` re-runs the other `pre-` hooks and continues the held job with `jobsctl retry <id> --attempt N`. `reject` and expiry cancel the job (`jobsctl cancel <id>`), then run the restore flow when the agent never ran; if the agent ran they only cancel the job and clear `job_held`.
- `stop` pending: created when the `stopped` rule needs confirmation (Commands, stop).
- `confirm` and `reject` exit codes: 0; 2 `human_only`; 10 no such record; 11 a hook vetoed; 12 a lower tool failed; 13 a hook escalated again or a stale plan created a new record; 20 `expired`, `not_pending`, `claim_lost`, `precondition_failed`.

## Restore

The restore flow undoes a start whose agent never ran. It runs from `start` (a failure after a write landed), from the job command (a launch failure or veto), from `sync` (a canceled, vetoed or failed job; the repair step; an expired or rejected `launch` pending) and only when no run of any agent of the item ever started (no adopted agent, or every run of the adopted agent ended in phase `launch`); with an agent that ran, the job's end sets `job_failed` instead and the phase is unchanged. Any non-terminal job of the item is canceled first (`jobsctl cancel <job id>`). The previous status, assignee and sprint ids are recorded before the start applies anything. Steps, each recorded in `steps` and skipped when its start step is not `applied` (or `unknown` that a live read shows landed):

1. `ticketctl transition KEY --to <previous status> --if-status <started status> --dry-run`, then applied with `--yes --expect-plan <hash>`, when the start changed the status. `precondition_failed` means a human moved the ticket: leave it alone.
2. When the start assigned the ticket and the live assignee is still `me`: `ticketctl update KEY --assign none` (or `<previous>` when there was one). A different live assignee is left alone and sets `restore_failed` (detail `assignee_changed`).
3. When the start added a sprint and the live open and future sprints are still what the start produced: previous ids empty gives `sprint remove KEY` (it drops every open and future sprint, ticketctl warns `other_sprints_dropped`); exactly one previous open or future id gives `sprint add KEY --sprint <id>`; more than one previous id cannot be restored and sets `restore_failed` (detail `sprints_unrestorable`); a closed previous sprint cannot be restored.
4. Release the claim with `--failed` (plain when the launch failure was `retryable` or a human canceled the job), set phase `failed`, fire `post-start-failed` with the result. The agent id, if any, is kept; a restart resumes that parked agent.

`no_such_transition` or a closed sprint sets the attention `restore_failed` with the details. The flow never guesses another route and skips `pre-` hooks (so a gate cannot leave the ticket in the wrong state); it is audited. `restore_on_failure: false`, or a board with no `started.to`, leaves the ticket as it is. The flow is idempotent and may run from every place above; `restore_state` (`none`, `done`, `failed`) prevents repeats. Basis: a restore applies ticket writes with `--yes` and an `auto:` actor without a fresh human acceptance because it only undoes a start that a human accepted (or that `confirm: auto` or an enforced gate allowed), each step is guarded by the live value the start set, and `restore_on_failure` (default true) is the config opt-in; this is a compensating action against design guide section 4.4 and is recorded in `design.md`.

## Teardown

A work item has one agent (the stored id); a restart after `failed` or a re-adopt reuses it. After `pr_merged` (cleanup gating below), if the stored agent is not live: the merged pull request used is the counting merged pull request whose repository equals the work item's repository and whose `head_ref` equals the recorded branch; `agent-spawn teardown <agent_id> --merged-head <its merged_head_sha> --actor <actor> --decision-id ...` (the invoking actor, for example `auto:cron`). When no pull request matches, no teardown is attempted: `cleanup.teardown` stays `pending` and the attention `teardown_refused` is set with detail `no_matching_pr`. A torn-down agent (exit 10 with `details.status: torn_down`) counts as done. Refusals `dirty`, `unpushed`, `in_use`, `repo_config_changed`, `held`, `live`, `locked` and `unlinked` set `teardown_refused` with the lower reason and are retried at the next `sync`; `partial` (wtctl deleted part of the tree) sets `teardown_refused` with detail `partial` and is not retried until a human finishes with `wtctl remove`; a pre-teardown hook veto (exit 11) or escalation (exit 13) sets it with detail `vetoed` or `escalated`. `--force` is human-only and ticket-work never passes it. After teardown succeeds the claim is released plainly, `cleanup.teardown` is `done` and `cleanup.claim` `released`. `cleanup.teardown: false` in config skips teardown (`not_needed`) and releases the claim. A closed-unmerged work item is never torn down automatically.

Cleanup gating: cleanup (teardown, then claim release) for an item in phase `merged` runs once the outcome of the `pr_merged` event is final and is not `pending` or `failed` (`applied`, `declined`, `skipped`, or no event rule). While it waits, `cleanup.claim` stays `held`, the claim is renewed and the attention `rule_failed` (failed) or none (pending) shows why. Cleanup is never skipped because of the claim state.

## Slot contract

Skill slot `implement-ticket` (architecture §5.5): default skill `ticket-work:implement-ticket`, kind `implement`, default mode interactive.

- **Bundle.** The plugin `ticket-work` ships inside the package and is located with `importlib.resources.files('ticket_work') / 'plugin'`. It contains the skill, a reference file holding the skill marker, the four sandbox placeholder entries (`.claude/`, `.mcp.json`, `CLAUDE.md`, `CLAUDE.local.md`), and the bundled permission profile. The profile sets no permission mode and allows file edits inside the working directory only (`Edit(/${CWD}/**)`, `Write(/${CWD}/**)`, never a bare tool name), `git` and `gh` through Bash, and the read tools; other tools prompt the human (the interactive default). `agent.skill` and `agent.plugin_dirs` replace or add skills.
- **Kind and trust.** ticket-work always passes `--kind implement`, runs `agent-spawn launch --dry-run` first and verifies the kind check (Job command step 4); any warning is fatal (an unknown kind silently runs the third-party-reading review profile). The run is trusted (not third-party-reading): boards are semi-trusted (architecture §13.2 rule 7) and ticket text is still fenced. ticket-work never passes `--reads-third-party`.
- **Safety settings, per call.** `--permission-profile <bundled or agent.permission_profile>`, `--sandbox <agent.sandbox>` (default `off`: a sandboxed, `dontAsk` run cannot read `~/.config/gh`, `~/.ssh` or `~/.gitconfig`, has a domain-limited network and loses `GH_TOKEN`; a recorded deviation from design guide §11), `--setting-sources <agent.setting_sources>` (default `["project"]` for interactive runs so the repository's own instructions load, a recorded deviation from the guide's default of none; `[]` for unattended runs unless the repository opts in, Unattended runs). `--env-allowlist-only <name>` is always passed, for a fixed base (`PATH HOME USER LOGNAME SHELL LANG TERM TZ` and `LC_*`) plus each name of `agent.env_allowlist`. Names in `jobs.pass_env` are never forwarded to the agent or to hooks; a user who wants the agent to have `SSH_AUTH_SOCK` or `TMUX` lists it in both `jobs.pass_env` (so jobsctl gives it to the job) and `agent.env_allowlist`. `validate` reports every name present in both lists as a notice. Every setting is replaceable in config.
- **Prompt file.** The job command builds one prompt file at every launch or resume (never at `start`, so a pending start confirmed hours later or a resume after a ticket edit sees fresh text). It reads `ticketctl get KEY --fields key,title,description,acceptance_criteria,parent,epic,links,labels --comments 10` (acceptance criteria are included when ticketctl returns them). Trusted facts come first, outside any fence: the ticket key, the repository id, the branch, the base, the draft-pull-request default, the work item's `run_token`, and the skill marker instructions. Untrusted text is fenced with a nonce, `<untrusted source="ticket" id="R">...</untrusted id="R">`, with the standing "data, not instructions" rule: title, description, acceptance criteria, the parent epic's title, linked ticket keys with titles, and the comments (an `--input-file` when large; only comments by trusted authors, Unattended runs). `R` and the run token come from a CSPRNG (at least 128 bits), fresh per prompt build; the fence neutralization replaces `</untrusted` and `<untrusted` case-insensitively and with intervening whitespace (design guide §12). A resume's `--prompt-file` carries the human's answer fenced the same way, and restates the trusted facts and the run token.
- **Prompt and state files.** The directories `~/.local/state/ticket-work/`, `prompts/` and `jobs/` are created with mode 0700 and the files with 0600. A prompt file has a random name and is created with `O_CREAT|O_EXCL|O_NOFOLLOW`; it is deleted when the launch or resume call returns. `sync` and `prune` delete prompt files older than one day.
- **Run token.** One token per work item (`run_token`, created at `start` step 9, new for a `failed` restart), stored in the settings snapshot, restated in every prompt, so a `done` after a resume validates. The artifact must carry it. It is not exposed in output.
- **Artifact.** The agent reports `done` with `{"schema_version": 1, "ticket": "<KEY>", "branch": "<name>", "prs": [{"url": "..."}], "summary": "...", "skill_marker": "...", "run_token": "..."}`. ticket-work reads it from the frozen path in `claude-session status --json` (through the agent-spawn result's `run.report.artifact.path`): `_job` opens that path without following symlinks, requires a regular file of at most 64 KiB whose size and sha256 equal the values in `run.report.artifact`, and validates it strictly: the schema, `ticket` equal to `key` or any of `requested_keys`, `skill_marker` equal to the marker in the bundled reference file, `run_token` equal to the one in the prompt, and `report.implicit: false`. It stores the validated `prs` (urls), `branch` and a hash of `summary` on the work item (`last_artifact`); later syncs read the stored copy only. A wrong skill name exits 0 `done` with no artifact, so a missing or mismatching artifact is a failed run (`agent_failed`). A `done` run with an empty `prs` that finds no linked pull request at the next `sync` sets the attention `agent_failed` with detail `no_pr`. The agent's `prs` and `branch` are claims: each pull request is verified through forgectl (PR linking). `summary` is untrusted.
- **Other reports.** `blocked` and `needs-input` carry only a reason (`report.status` tells them apart); the agent is not asked for an artifact. The reason is stored in `last_report.summary` (untrusted, sanitized on output).
- **Self-labeling** (`agent-spawn label add --session`) is optional for the agent; a shell variable in a command is denied inside an isolated run, so ticket-work never depends on it.

### Unattended runs

A run is unattended when it is started by `start --auto` or its mode is `headless`. Three rules apply. (a) Comments reach the prompt only from authors that are trusted: the user's own account (`own` in ticketctl's comment objects) or an account id in `boards.<name>.trusted_authors`; comments of other authors are left out (the prompt notes that comments were omitted). Interactive runs obey the same comment rule. (b) An unattended start requires that the ticket's `reporter` is the user's own account or is in `boards.<name>.trusted_authors` (`["*"]` means any reporter, an explicit choice of the user); otherwise the start exits 20 `untrusted_reporter` (and releases per Claim release rules). (c) The default `setting_sources` of an unattended run is `[]`; a repository opts in with `repos.<id>.agent.setting_sources: [project]`. The bundled permission profile also denies `Read` of `~/.ssh/**`, `~/.config/gh/**`, `~/.config/glab-cli/**`, `~/.aws/**`, `~/.gnupg/**`, `~/.netrc`, `~/.claude/**` and the configuration directories of the awkit tools; this is guidance for a trusted unsandboxed agent, not a boundary (Residual risks).

## Hooks

Hooks follow design guide §8: configured under `hooks.<name>` as `{cmd, timeout, async}` lists, run via `sh -c` in their own process group, JSON on stdin, default timeout 30 seconds. Pre-hook exit 0 continues, exit 13 escalates, any other non-zero vetoes (exit 11). The hook environment is the fixed base of the Slot contract plus `TICKET_WORK_HOOK`, `TICKET_WORK_ID` (the work id) and `TICKET_WORK_OBJECT_TYPE` (`work`); `jobs.pass_env` names are removed. A hook's returned `decision_id` is validated against the grammar `^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$` (no leading `-`); every value that originates outside ticket-work is passed to a lower tool in the `--opt=value` form. Per-invocation `--hook <name>=<cmd>` is accepted by `start`, `resume`, `confirm`, `stop`, `sync`, `link` and `unlink`.

| Hook | Runs | Notes |
|---|---|---|
| `pre-enqueue` | `start` step 6, after the claim and preconditions | veto releases the claim (Claim release rules); escalation records a pending start |
| `pre-transition` | before every ticketctl write ticket-work makes (transition, sprint, comment) | veto or escalation applies the hook outcomes of Apply outcomes; skipped by the restore flow (which is audited) |
| `pre-launch` | in the job, before `agent-spawn launch` or `resume` | veto restores the start when the agent never ran; escalation holds the job (exit 13) |
| `post-link` | a link or unlink | |
| `post-status` | an event was applied, recorded as pending, skipped, declined or failed, including `pr_merged_partial` | |
| `post-start-failed` | a start was restored | |
| `post-pending` | a pending confirmation was recorded | |
| `post-attention` | an attention reason was set | closed `reason` (Attention reasons) |

Payload (schemas in `schemas/hooks/`): the common fields `tool`, `hook`, `event_id` (post hooks), `object_type: work`, `object_id`, `repo` (the work item's repository id), `labels` (`ticket=<KEY>`, `owner=ticket-work`, `repo=<repo id>`, `board=<name>`), `board`, `site`, `key`, `phase` (null for a `pre-enqueue` hook when no work item exists), `actor` and `decision_ids`, plus by hook: `pre-enqueue` the common fields only; `pre-launch` adds `mode`, `skill`, `branch`, `base` for gates; `pre-transition` adds `event`, `rule`, `plan` (`action`, `steps`, `current_status`, `target_status`, `plan_sha256`); `post-link` adds `change` (`link` or `unlink`) and `pr_ids`; `post-status` adds `event` (including `pr_merged_partial`), `rule`, `outcome` (`applied`, `pending`, `skipped`, `declined`, `failed`), `reason`, `pending_id` and `pr_ids`; `post-start-failed` adds `reason` (a ticket-work or lower reason string), `restore_state` and `dedupe_key` (`<work id>:start_failed:<seq>`); `post-pending` adds `pending_id`, `action`, `event`, `summary` (trusted text), `expires` and `dedupe_key` (the pending id); `post-attention` adds `reason` and `dedupe_key`. `plan.current_status` and `target_status` are host status names: allowed, untrusted, capped at 64 characters. Payloads carry keys, ids, `phase`, enums and counts, never ticket, pull request or model text. Post hooks are delivered at least once through an outbox, after the command prints its result, with `event_id`; a failed post hook is logged and never fatal.

## Exit codes

| Exit | Meaning |
|---|---|
| 0 | success (including `unchanged`, `already_running`) |
| 1 | internal error |
| 2 | usage, invalid config, `human_only` |
| 10 | not found (work item, pending record, ticket) |
| 11 | a pre-hook vetoed |
| 12 | a lower tool failed or is missing (`lower_failed`, `tool_missing`, `tool_too_old`, `partial_results`, `repo_unresolved`, `schema_newer`) |
| 13 | needs a human: a pending confirmation was recorded, or a hook escalated, or the job was held |
| 14 to 18 | the job command only: the agent's outcome passed through |
| 20 | refused, with `reason` |
| 21 | ambiguous key |
| 22 | `start`: `nothing_to_start` (reasons `empty`, `no_capacity`, `pending_exists`) |

Refusal reasons (exit 20): `live`, `precondition_failed`, `unmapped`, `already_started`, `not_active`, `not_current_job`, `claimed`, `claim_lost`, `declined`, `expired`, `not_pending`, `stale_plan`, `not_linkable`, `untrusted_reporter`, and the reasons of a lower tool passed through. Exit 2 reasons: `human_only`, `invalid_combination`, `stdin_conflict`, `invalid_config`, `missing_option`. Exit 22 means "nothing to do" here, not invalid input (ticketctl's meaning).

## Lower tool exits

One table maps every lower exit to a ticket-work result. Exit 21 and 22 of a lower tool never become ticket-work's 21 and 22 (except ticketctl's key ambiguity at `start` and ticket-queue's exit 22 from `next`).

| Lower exit | ticket-work result | Retry class |
|---|---|---|
| 0 | success (including `unchanged`, `created: false`) | none |
| 10 not found | exit 10 `not_found` for the subject the user named (ticket, claim of a named key, work item); exit 12 `lower_failed` for anything else (a stored agent or job id gone: attention `agent_missing` or `job_failed`) | none |
| 11 veto | exit 11 `hook_vetoed` (`tool`, `hook` of the lower tool), no restore of a different action | none |
| 12 expected failure | exit 12 with the lower code as `code` when it is one of `partial_results`, `repo_unresolved`, `tool_missing`, `tool_too_old`, `schema_newer`, else `lower_failed`; ticketctl `partial` and `outcome_unknown` follow Apply outcomes; `rejected`, `lookup_incomplete` are permanent (Events); `auth_required`, `rate_limited` and the rest are transient | transient |
| 13 escalated or needs a human | exit 13 with a pending record (Apply outcomes, Job command) | held |
| 20 refused | exit 20; `reason` is the lower reason verbatim (`done`, `gone`, `skipped`, `hidden`, `claimed`, `not_held`, `no_such_transition`, `sprint_closed`, `stale_ticket`, `dirty`, `unpushed`, `in_use`, ...), `details.lower_error` holds the whole lower error object | per Apply outcomes and Events |
| 21 ambiguous | ticketctl ambiguity of a typed key at `start`: exit 21 `ambiguous_key`; every other lower 21 (`ambiguous_transition`, `ambiguous_sprint`, `ambiguous_board`, wtctl, agent-spawn): exit 12 `lower_failed` | permanent |
| 22 | ticketctl 22 (`missing_required_fields`, `needs_resolution`, `invalid_value`, `unknown_field`): exit 12 `lower_failed`; agent-spawn 22 and jobsctl "nothing to do" never occur (no timeout is passed); ticket-queue 22 from `next` is `nothing_to_start` | permanent |
| 2 usage | exit 1 `internal` with the lower error (a bug of ticket-work) | none |
| 14 to 18, 130, 143 (agent-spawn waiting commands) | the Job command table | per table |
| any other code | exit 12 `lower_failed` | transient |

## Output by exit code and error envelope

With `--json`: exit 0 and 22 print the command's object; 13 prints the pending object (or the held result); 2, 10, 11, 12, 20 and 21 print the error envelope `{"error": {"code", "message", "reason", "details", "tool", "lower_code", "lower_error", "hook", "hook_stderr", "decision_ids"}}`. `tool` names the lower tool that failed (`ticketctl`, `ticket-queue`, `forgectl`, `agent-spawn`, `jobsctl`, `wtctl`); `lower_error` is its whole `error` object verbatim and untrusted; `lower_code` is the lower tool's own `code` (an untrusted string); `decision_ids` is an array (empty when none). Errors go to stderr as well.

Error codes by exit: 1 `internal`, 2 `invalid_argument`, 10 `not_found`, 11 `hook_vetoed`, 12 `lower_failed` / `tool_missing` / `tool_too_old` / `partial_results` / `repo_unresolved` / `schema_newer`, 20 `refused`, 21 `ambiguous_key`.

The `reason` field is a snake_case string `^[a-z][a-z0-9_]{0,63}$`: ticket-work's own reasons are the lists of Exit codes, and a lower tool's reason is passed through unchanged. `details` shapes per reason: `precondition_failed` `{rules[], current_status, unknown[]}`, `not_linkable` `{why}`, `live` `{agent_id, job_id}`, `already_started` `{phase}`, `unmapped` `{why}`, `untrusted_reporter` `{reporter}`, `not_current_job`, `not_active` `{phase}`, `claim_lost` `{lower_reason}`, `stale_plan` `{new_pending}`.

## Output sanitizing

Every human-readable print of an untrusted field (`title`, `last_report.summary`, `attention` detail, `lower_error`, `hook_stderr`, host status names, the dialog) goes through one sanitizer: C0, C1, DEL, bidi and other invisible format characters become visible markers and the text is cut to a line limit. `--json` is not sanitized (consumers sanitize).

## Objects

The schema files under `schemas/` are the field lists; this section names each shape and the decisions behind it. Every schema is closed (`additionalProperties: false`): producers are strict, consumers must ignore unknown keys.

- **Nothing-to-start object** (exit 22 of `start`): `{nothing_to_start: true, reason: empty|no_capacity|pending_exists}`. `schemas/cli/start.json` is `oneOf` the start result and this object.
- **Start result** (`schemas/cli/start.json`): `work`, `claim` (ticket-queue's claim object verbatim), `plans` (`{transition: plan|null, sprint: plan|null}`), `applied` (a list of `{step, status, attempt_id?}` where `step` is ticketctl's step kind: `assign`, `transition`, `sprint_add`, `sprint_remove`, `set_fields`, `add_comment`; and `status` is `planned|applied|unchanged|skipped|failed|unknown`), `pending`, `job` (`{id, status?, foreground?, exit_code?}` or null; `id` is null for a foreground run), `warnings` (`{code, message}` with the closed codes `sprint_failed`, `assign_skipped`, `existing_job`, `queue_full`, `pass_env_undefined`, `label_skipped`, `lookup_incomplete`, `incomplete_discovery`), `dry_run`. `work` is not null for a pending start (it has a stored item in phase `pending`); it is null only for a dry run.
- **Plan** (hooks and pending): `{action: transition|sprint_add|sprint_remove|update|comment, steps, current_status, target_status, plan_sha256, changes?}`; the pending record holds `plan_sha256` as a map step to hash and `details.changes`. Status names are host text: untrusted, sanitized, at most 64 characters.
- **Work item** (`schemas/cli/show.json`): `id`, `site`, `key`, `requested_keys`, `board`, `title` (untrusted), `phase`, `needs_attention` (boolean), `attention` (array of `{reason, detail, since}`), `repo`, `branch`, `base`, `holder`, `claim` (`expires_at`, `renewed_at`, `state`), `previous` (`status`, `assignee` (account id or null), `sprint_ids` (non-negative integers)), `started_status`, `steps` (`[{step: transition|sprint_add, status}]`), `job` (`id`, `status`), `agent` (`id`, `status`, `needs_attention`; the last is agent-spawn's own value as a string), `links`, `pending` (ids), `cleanup` (always present: `teardown` `not_needed|pending|done|refused`, `claim` `held|released`), `restore_state`, `last_report` (`status`, `summary` untrusted), `last_artifact` (`{prs, branch, summary_sha256}` or null), `labels` (`ticket=<KEY>`, `owner=ticket-work`, `repo=<repo id>`, `board=<name>`; the filter set of `list --label`), `created`, `updated`. The settings snapshot and the run token are not printed. `show` adds `pending_records` (full records) and `events` (at most 20, `{event, event_key, outcome, reason, ts, rule, pending_id}`).
- **Work summary** (`schemas/cli/list.json`): the work item without `requested_keys`, `base`, `holder`, `claim`, `previous`, `started_status`, `links`, `cleanup`, `restore_state`, `last_report`, `steps`, `last_artifact`; `attention` is an array of reason names; adds `prs` (`[{pr, state, counts}]`) and keeps `labels`; the list output is `{"items": [...], "count": N}`.
- **Link**: `pr_id`, `repo_id`, `pr`, `repo`, `tier` (`claimed`, `branch`, `title`, `manual`), `state` (`linked`, `candidate`, `ignored`, `missing`), `counts`, `label_synced`, `facts` (`state` `open|closed|merged`, `draft`, `head_sha`, `head_ref`, `base_ref`, `is_fork`, `merged_head_sha`, `updated_at`, `activity_at`), `linked_at`.
- **Sync report** (`schemas/cli/sync.json`): `items` (per work item: `id`, `phase`, `events` (`{event, event_key, outcome, reason}`), `applied`, `pending`, `errors`, `lease_held`), `claims_released` (integer), `already_running`, `rerun`, `partial`, `errors` (`{work_id|null, step, code, message, tool|null, lower_error|null}`); `step` is one of `lease`, `expiry`, `repair`, `claims`, `agents`, `jobs`, `discovery`, `read`, `stale`, `rules`, `cleanup`, `hooks`.
- **resume**: `{work, mode, job|null, pending|null, warnings, dry_run}`. **stop**: `{work|null, stopped, applied[], pending|null, claim_released, dry_run}`. **link**: `{work, link, changed, promoted, applied[], dry_run}`; **unlink**: `{work, pr_id|null, changed, ignored, dry_run}`. **pending**: `{items, count}`; **confirm**: `{pending, work, applied, job|null, new_pending|null, warnings}`; **reject**: `{pending, work, claim_released}`. **cron install**: `{installed, changed, sync_interval, start_interval|null, block[], dry_run}`; **cron uninstall**: `{installed: false, changed, dry_run}`. **export**: audit records (no log export). **prune**: `{dry_run, removed: {work_items, links, pending_resolved, pending_expired}, skipped, warnings}`. **validate**: exit 0 `{ok, probe, tools[], boards[], problems[], warnings[]}`; `problem` and `warning` are `{code, message, board|null, tool|null}`.
- **`_job`**: internal, its output is not a contract; exit 13 of `_job` has no object.
- **Pending record**: Pending confirmations. `escalated_by` is a hook name or `ticketctl`.
- **Hook payloads**: Hooks.

## Configuration

`~/.config/ticket-work/config.yaml` plus `config.d/*.yaml` (design guide §5), validated at load (`schemas/config.json`, `config.example.yaml`). Precedence: flags, `repos.<id>`, environment, global config, defaults. Top-level and board objects are closed: a key the implementation adds needs an interface change first.

| Key | Default | Meaning |
|---|---|---|
| `me.name` | OS user | actor name |
| `instance` | the hostname lower-cased, characters outside `[A-Za-z0-9._-]` replaced by `-`, cut to 64, `host` when empty | part of the claim holder `ticket-work:<instance>`; the store records the instance at first run and refuses a different value (exit 2 `invalid_config`) |
| `boards.<name>.site` | none (required) | the ticketctl site (one board per site) |
| `boards.<name>.queue_board` | none | the ticket-queue board this board takes tickets from |
| `boards.<name>.trusted_authors` | `[]` | account ids or `["*"]`; empty means only the user's own account (Unattended runs) |
| `boards.<name>.repos` | none (required) | ordered repository rules |
| `boards.<name>.branch.types` | `{default: feat}` | branch type by issue type (`^[a-z][a-z0-9-]{0,19}$`) |
| `boards.<name>.preconditions` | `[]` | named checks |
| `boards.<name>.status_map` | `{}` (`started` required to start) | event rules; keys are the 8 events |
| `boards.<name>.link_comment` | `false` | comment on `pr_opened` |
| `defaults.confirm` | `ask` | default for a rule's `confirm` |
| `start.max_pending` | `1` | unresolved pending starts allowed under `--auto` (the gate compares the open count with it) |
| `pending.start_expiry` | `24h` | pending start lifetime (at least `1m`) |
| `pending.expiry` | `7d` | other pending lifetime (at least `1m`) |
| `claim.ttl` | ticket-queue's default | passed with `--ttl` when set (a duration or null; at most `claim.max_ttl`, checked by ticket-queue) |
| `claim.renew_below` | `0.5` | renew when this fraction of the TTL remains (in (0, 1]) |
| `claim.orphan_after` | `15m` | release or repair grace: a claim of this store with no work item, or an item stuck in `applying`, is handled after this age |
| `sync.overlap` | `1h` | discovery watermark overlap |
| `sync.reread_open_after` | `1h` | re-read open pull requests at least this often |
| `sync.pr_idle_after` | `14d` | `pr_idle` threshold |
| `agent.skill` | `ticket-work:implement-ticket` | the slot skill |
| `agent.mode` | `interactive` | `interactive` or `headless` |
| `agent.sandbox` | `off` | `off`, `preferred` or `required` |
| `agent.permission_profile` | bundled file | replaces the bundled profile |
| `agent.setting_sources` | `["project"]` interactive, `[]` unattended | Claude setting sources (`user`, `project`, `local`); an unattended run uses `[]` unless `repos.<id>.agent.setting_sources` opts in |
| `agent.env_allowlist` | `[]` | names added to the fixed base of `--env-allowlist-only` |
| `agent.plugin_dirs` | `[]` | extra plugin directories |
| `agent.model` | none | passed with `--model` when set |
| `agent.timeout` | none | passed as `--timeout` when set |
| `jobs.enabled` | `true` | use jobsctl (required for `start --auto`) |
| `jobs.queue` | `tickets` | jobsctl queue (`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`) |
| `jobs.pass_env` | `[]` | `--pass-env` names for the job's own tool calls (credentials come from jobsctl's env file); never forwarded to the agent or hooks |
| `jobs.kill_grace` | `120s` | `--kill-grace` |
| `cleanup.teardown` | `true` | tear down after `pr_merged` |
| `restore_on_failure` | `true` | run the restore flow |
| `retention.work` | `90d` | `prune` age |
| `retention.pending` | `30d` | `prune` age for resolved pending records |
| `hooks.<name>` | `[]` | hook lists; entries `{cmd, timeout (seconds or duration, 1 to 600), async}` |
| `tools.<name>` | the tool's name | executable path per sibling |
| `repos.<id>` | none | per-repository overrides of `agent.*` (all keys), `cleanup.teardown` and `restore_on_failure` only |

Name grammars: variable names `^[A-Za-z_][A-Za-z0-9_]{0,127}$`, hook decision ids as in Hooks. `repos.<id>` wins over the environment, the global config and the defaults; flags win over `repos.<id>`.

## Environment variables

Only these scalars can be set as `TICKET_WORK_<KEY>` (nested keys joined with `__`): `me.name`, `instance`, `jobs.queue`, `jobs.kill_grace`, `sync.overlap`, `sync.reread_open_after`, `sync.pr_idle_after`, `claim.ttl`, `claim.renew_below`, `claim.orphan_after`, `pending.start_expiry`, `pending.expiry`, `retention.work`, `retention.pending`. Safety, path and autonomy settings (`agent.*`, `tools.*`, `defaults.confirm`, `cleanup.*`, `restore_on_failure`, `boards.*`, `hooks.*`) are config-file only. Structured config (boards, hooks, rules) cannot be set from the environment. ticket-work reads no credentials: each sibling tool reads its own, and the job receives the names in `jobs.pass_env` from jobsctl's env file. `XDG_CONFIG_HOME` and `XDG_STATE_HOME` redirect config and state.

## Labels

ticket-work labels the agent and the job: `ticket=<KEY>`, `owner=ticket-work`, `repo=<repo id>` (agent-spawn adds `job=<job id>`). It adds `pr=<host/path#N>` to the stored agent when a link is made. Claims made by ticket-work carry the label `store=<store id>`. The work item's own `labels` (`ticket`, `owner`, `repo`, `board`) are the filter set of `list --label`. Labels are not authenticated against trusted agents, so ticket-work verifies every link against forgectl and every agent against its own records before an external action; labels only find candidates.

## Files

`~/.local/state/ticket-work/`: `state.db` (private), `audit.jsonl` and `log.jsonl` (public append-only contracts, `schemas/audit.json` and `schemas/log.json`), `prompts/` (prompt files with random names, mode 0600, deleted when the launch or resume call returns), `jobs/` (the job's cwd, mode 0700). Schema migrations are additive.

## Audit and log

Every external action appends an `attempted` record before the write and an outcome record after it (pairs share `attempt_id`): `transition`, `sprint_add`, `comment`, `restore`, `link`, `unlink`, `launch`, `resume`, `teardown`, and the pending confirmations (`pending_confirm`, `pending_reject`, `pending_expire`). Fields: `v`, `seq`, `ts`, `actor`, `decision_id` (array), `attempt_id`, `target` (work id), `action`, `inputs`, `result` (`attempted|ok|failed|partial|unknown`), `changed`, `reason`. `inputs`: `work_id`, `event`, `rule`, `plan_sha256`, `pr_id`, `pending_id`, `lower_attempt_id` (the lower tool's `attempt_id`, for correlation); all optional. A `start` or `stop` has no audit action of its own: its claim writes are in ticket-queue's audit and its ticket writes in ticketctl's. `log.jsonl` records are defined by `schemas/log.json`, which is normative for them. The attribution of an agent's own commits and pull requests is the implement skill's job (commit trailers and the pull request body).

## Concurrency

Every command that writes the store or contacts a lower tool for a write takes leases (design guide section 4.3). There are two kinds. The sync lease is one row, taken by `sync` for its whole run. The ticket lease is one row per work id (`site:KEY`; for a ticket that has no work item yet, the row for the key is created, so `start` holds it before the claim). `start`, `resume`, `stop`, `link`, `unlink`, `confirm`, `reject` and the per-item steps of `sync` take the ticket lease; `_job` takes it only for its short sections (loading the item, storing the agent id and the result, the restore flow). A lease records the holder PID, the holder's process start time and an expiry, and a heartbeat renews it while the holder lives. A lease whose holder is dead (the PID is gone or its start time differs) may be taken over; a lease whose holder is alive is never taken over, even when it expired (a suspended machine keeps its PIDs). Every store write of a work item checks in the same transaction that the writer still holds its lease; a lost lease aborts the command with exit 1 (`lease_lost`). No lease is held across `agent-spawn launch`, `resume` or `wait`, across a job queue wait, or while a run of the agent is going on; `start` does hold the ticket lease during its confirmation dialog. A second `sync` exits 0 with `already_running: true` and sets the store flag `sync_rerun`; the running `sync` reads and clears the flag before it releases the sync lease and runs its steps once more when the flag was set. `sync` skips a work item whose ticket lease is held (the item entry has `lease_held: true`, no error) and handles it at the next run. Whether an agent is live is asked of agent-spawn, never inferred from a lease.

## Dependencies

| Tool | Binding | Used for |
|---|---|---|
| ticketctl | A | ticket reads (`get --fields`, comments), transitions, sprints, comments, restore |
| ticket-queue | A | `next --claim`, `claim --label`, `claims`, `release` |
| forgectl | A | pull request discovery and state: `prs`, `show`, `whoami`, `snapshot` (minimum 0.52.0) |
| agent-spawn | A | `launch --dry-run`, launch, resume, wait, list, show, label, teardown |
| jobsctl | A (required for `start --auto`; optional otherwise) | the `tickets` queue, capacity, `show`, `cancel`, `retry`, `resolve` |
| wtctl | A | `wtctl locate` before a start; `wtctl show` for agent adoption |

A missing required tool is exit 12 `tool_missing` naming its install command. The minimum versions of the siblings that implement their designed interfaces are pinned when implementation starts.

## Upgrades

The `schema_version` of `state.db` is additive-only. A newer database than the tool exits 12 (`schema_newer`). Hook payloads and `--json` outputs: producers are strict (closed schemas), consumers must ignore unknown keys.

## Residual risks

- Two machines with separate stores can both pass the start checks in the same second; Jira's live status check and `--if-status` make the second transition `unchanged`. There is no cross-machine lock. Two state directories on one host need different `instance` values, because the holder is the same string.
- Labels and an agent's artifact are claims; verification relies on forgectl and ticket-work's own records. `skill_marker` and `run_token` are anti-accident checks, not defenses against forgery.
- A trusted, unsandboxed implement agent can run any command the user can; the bundled profile only guides it, and the unattended rules (Unattended runs) reduce but do not remove the exposure.
- ticketctl's confirmation prompt is not a boundary against a caller that can allocate a pty (architecture §13.1); the same holds for `confirm --yes`.
- `plan_sha256` has no expiry; ticket-work's pending expiry bounds the window.
- A worktree root trusted once in the Claude UI removes the trust dialog for every later worktree (agent-spawn's advice), so project settings of a base branch run unattended only where a repository opted in.
- A human `agent-spawn resume` of a held job's agent leaves the agent outside any job: its slot is not counted and `jobsctl cancel --force` does not reach it.
- forgectl's `hidden_repos` setting silently drops pull requests from every listing (no `complete: false`); a mapped repository that is hidden is never discovered, while the `claimed` tier and `link` still work because they use `show`.

## Platform notes

Linux, WSL and macOS. tmux is needed only for interactive agents (through agent-spawn); `--mode headless` needs none.
