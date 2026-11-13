# ticket-work: interface

Status: 0.1.0-design (2026-11-13). This document is the single normative source for ticket-work's rules. `design.md`, the README and the architecture link to its headings and never restate its tables. Section references (architecture §N, design guide §N) point to `../awkit-docs/architecture.md` and `../awkit-docs/design-guide.md`.

ticket-work owns the lifecycle of a worked ticket: it claims a ticket, applies the board's start changes (assignment, sprint, status) after a confirmation, launches an implement agent in its own worktree, links the agent's pull requests to the ticket, applies a per-board status map as those pull requests move, and tears the work down after the merge. It is a workflow tool (layer 3) and a skill wrapper for the `implement-ticket` slot (design guide §11). It works standalone from a terminal and from cron; it never depends on the harness.

## Overview

- **Work item.** One record per worked ticket. The work id is `<site>:<KEY>`, where KEY is the key as typed or claimed at creation, and never changes; `key` is the current canonical key (read at start step 3) and `requested_keys` lists every earlier or requested key (a moved ticket). A `site:KEY` or bare key given to any command is matched against the store by the Lookup rule below. Everything derived from a key at creation (the job unique key, the agent and job labels, the branch) stays as created; every lookup (adoption, label search, branch token matching, artifact `ticket` validation) uses the union of `key` and `requested_keys`. The `site` is a config site name (at most 32 characters); the key follows ticketctl's grammar; the whole id fits `^[A-Za-z0-9._:-]{1,128}$` and contains neither whitespace nor `/`. The record lives in ticket-work's own store (`state.db`); everything another tool owns (the claim, the ticket, the pull request, the job, the agent) is re-read from that tool on each `sync`. The store holds only what no other tool owns: the previous status and sprint ids for a restore, the write-ahead step list, the pending confirmations, the claim holder, the job id or foreground marker, the agent id, the linked pull requests with their last-seen facts, the applied events and the attention reasons.
- **Board.** A named config entry with a ticketctl `site`, the rules that map a ticket to a repository, the branch naming, the preconditions and the status map. A site has exactly one board. ticket-work boards are bound to ticket-queue boards by `queue_board` (optional), never by name.
- **Link.** The relation between a work item and a pull request, recorded with the evidence that justified it (`tier`).
- **Pending confirmation.** A recorded action that needs a human (design guide §4.4).
- **Holder.** The opaque claim holder `ticket-work:<instance>` (see Configuration, `instance`).
- **Lookup.** A `KEY` argument is resolved the same way by every command (`start`, `resume`, `sync`, `show`, `stop`, `link`, `unlink`): `site:KEY` names the site; a bare key is matched against the store (work id, `key` and `requested_keys`) across all sites. Exactly one work item decides the work id; several exit 21 `ambiguous_key` (`details.candidates`); none falls back to `ticketctl sites resolve KEY --json` (offline, no network), whose exit 21 is passed through and whose site must be the site of a board (otherwise exit 20 `unmapped`, `details.why: no_board`). A `site:KEY` is matched against id, `key` and `requested_keys` of that site. The resolved work id is the lease key; a new work item takes the key as typed or claimed as its work id, and the canonical key from the first read as `key`.
- **Site flag.** Every `ticketctl` and `ticket-queue` call that concerns one work item carries `--site <site>` (or the `site:KEY` form), so a key can never be read from another site. Calls without a key (`next --claim`, `claims`) carry `--site` only where the command takes it.

pr-watch is not used in 0.x: `sync` reads the pull requests itself (one `show` per linked pull request). The harness rule "pr-watch event, then `ticket-work sync`" (architecture section 7.5) has no producer in 0.x, so `sync` from cron is the guaranteed path.

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
ticket-work prune [--older-than D] [--item KEY] [--dry-run]
ticket-work validate [--probe]
ticket-work _job WORK_ID            (internal; run by the job, see Job command)
```

`KEY` is a ticket key or `site:KEY`, resolved by the Lookup rule (Overview). `PR` is a URL or `host/<full project path>#N`. Ticket keys follow ticketctl's grammar and are printed upper-case.

### Global flags

`--json`, `--config PATH`, `--verbose`, `--quiet` (with `--verbose`: exit 2 `invalid_combination`), `--dry-run`, `--yes`, `--actor ACTOR`, `--decision-id ID` (repeatable), `--hook NAME=CMD` (repeatable), `--version`.

- `--dry-run` applies to every command that changes state or contacts another tool for a write: it stores nothing (including cursors), takes no lease and prints what would happen. `sync --dry-run` prints the events that would be evaluated; `resume`, `confirm`, `stop`, `link` and `unlink` print their plan.
- `--actor` follows ticketctl's grammar `^(human|auto):[A-Za-z0-9._@-]{1,64}$`. The default is `human:<me.name>` when stdin and stderr are TTYs and `/dev/tty` opens, otherwise `auto:unknown`. `cron install` writes entries that pass `--actor auto:cron`.
- `--yes` means the caller confirmed in its own dialog; it skips ticket-work's own confirmation dialog (Confirmation matrix). It is accepted only with a human actor; with an `auto:` actor it exits 2 (`human_only`). It never bypasses a precondition, a gate or a refusal. Automation never passes it (design guide §4.4).
- `--hook NAME=CMD` adds a hook for one invocation. It is accepted by `start`, `resume`, `confirm`, `stop`, `sync`, `link` and `unlink`; it is not carried into a job (the `pre-launch` hook of a job comes from config only) and is not config.
- Untrusted text never travels only in argv: `resume --prompt-file` takes a file or `-`. At most one `-` source per command (exit 2 `stdin_conflict`).
- `--config PATH` loads only that file (no drop-ins). It is forwarded in the job argv when a start used it.

### start

`start KEY` claims that ticket; `start` with no key takes the top eligible ticket (its key is known only after the claim, Start order step 2). `--board B` names a ticket-work board and limits the choice to that board's tickets: it passes `--board <queue_board>` to `ticket-queue next`, requires that `queue_board` is set (otherwise exit 2 `invalid_combination`), and the chosen ticket's site must equal B's site. `--skill`, `--mode` and `--sandbox` override the `agent.*` config keys for this start and are stored on the work item.

`start --auto` is the cron form: it is the only form that may run without a human. It takes no `KEY` and no `--yes` (exit 2 `invalid_combination`), requires jobsctl, applies the gate (Start order step 1), starts at most one ticket per run, may claim and refuse up to `start.scan_limit` candidates (Claim release rules), records a pending start unless the rule's `confirm` is `auto`, and never prompts.

The order of every start is fixed (Start order). A start that cannot proceed releases its claim (Claim release rules) and exits with the refusal. Output: the start result object (Objects).

Exit codes: 0 started (job enqueued, or a foreground job reported done); 2 usage (`invalid_combination`, `human_only`, `invalid_config`, `missing_option`); 10 the ticket was not found; 11 a `pre-enqueue` or `pre-transition` hook vetoed; 12 a lower tool failed; 13 a pending start was recorded, a hook escalated, or (foreground only) the job was held; 14 to 18 (foreground only) the agent's outcome passed through; 20 refused (`precondition_failed`, `unmapped`, `already_started`, `claimed`, `untrusted_reporter`, `declined`, `foreign_claim`, `job_key_taken`, `busy`, or a lower reason passed through); 21 ambiguous key; 22 `nothing_to_start` (reasons `empty`, `no_capacity`, `pending_exists`, `scan_exhausted`).

### resume

`resume KEY` continues the agent of a work item that is not finished. It requires phase `starting`, `working` or `in_review` and a parked agent (a live agent exits 20 `live`); when no agent id is stored it first runs Agent adoption, and with the result `none` or `unknown` it exits 20 `not_active` (`details.phase`, hint `start` or `sync`); while a `launch` pending is open it exits 20 `not_active` (hint `confirm`). `--mode` defaults to the mode of the agent's last non-promotion run; a human answering a blocked headless agent passes `--mode interactive`. `resume` recomputes `mode`, `unattended` and `setting_sources` of the settings snapshot from its own flags, the actor and the configuration (a run is unattended when its mode is `headless` or the actor is `auto:`), updates the snapshot in the same transaction that stores the job id, and when the run becomes unattended re-runs the Unattended runs rules (b) and (c) (a live reporter check, exit 20 `untrusted_reporter`). `--prompt-file` carries the human's answer (fenced by ticket-work like every untrusted text, see Slot contract; at most 64 KiB; `-` reads stdin at once); the answer is stored in `state.db` (`pending_answer`, private) and written by `_job` into the fenced prompt file when the job launches; a second `resume` before the launch replaces it.

`resume` that finds the claim lapsed (`ticket-queue claims` has no entry for the key, or a renewal answers `not_held`) takes a new claim (`claim KEY --site <site> --holder H --label store=<store id>`); only a refusal (the ticket is claimed by another holder, `done`, `gone`, `skipped`, `hidden`) exits 20 `claim_lost`.

If a job for this work item is held with hold reason `exit_13`, `resume` continues it with `jobsctl retry <id> --attempt N` (N is `attempt` from `jobsctl show`, same job id); a job held for another reason (`manual`, `escalated`) exits 20 `not_active` (`details.hold_reason`, hint `jobsctl release`); otherwise `jobsctl add` is called as in Start order step 11 (a terminal holder of the key does not block) and clears the attention `job_failed`. The job id and the snapshot are stored in one transaction. Without jobsctl it runs the job command in the foreground and exits as `start` does (Start order step 11).

Exit codes: 0 enqueued; 2; 10 no such work item; 11 a `pre-launch` veto (a foreground run only; otherwise the veto is raised later, in the job); 12 a lower tool failed; 13 a pending launch recorded (a foreground run only; otherwise raised in the job); 20 refused (`live`, `not_active`, `claim_lost`, `untrusted_reporter`); 21 ambiguous key.

### sync

`list` and `show` read only the store; `sync` is the periodic command and the only one that reads every tool. It is idempotent, safe under cron and takes a lease (Concurrency). The order is fixed (Sync order). `sync KEY` restricts every step to that work item and its repository, reads and updates that item's facts, and never advances a discovery cursor. `sync --dry-run` stores nothing (no cursor, no facts, no events): the report has `dry_run: true` and each item entry `would_events` (the names of the events that would be evaluated).

A human `sync` at a TTY shows all due `confirm: ask` plans together and asks once (the dialog times out after 10 minutes, a no): a yes applies them all, a no records nothing (the events stay due and are evaluated again at the next `sync`). Without a TTY, or with an `auto:` actor, each due plan becomes a pending confirmation.

Output: the sync report object. Exit codes: 0 (including "already running", `already_running: true`); 1 internal; 2 usage; 10 and 21 for `sync KEY` (no such work item, ambiguous key); 12 a lower tool failed (`lower_failed` for the whole run, `partial_results` for part of it; the report is printed with `partial: true` and the envelope's `details.errors`; the other items were still processed).

### list and show

`list` and `show` read only the store; they contact no other tool and run no hook. `list --json` prints `{"items": [<work item summary>...], "count": N}` ordered by `updated` descending. Without `--all`, items in phase `merged`, `stopped` or `failed` older than 24 hours are omitted unless they have an attention reason or an outstanding cleanup (`cleanup.teardown` `pending` or `refused`); `--needs-attention` ignores the age rule. `--board B` names a ticket-work board. `--phase` is repeatable (OR); `--label` filters the work item's `labels`; `--label` and `--pr` are ANDed; `--pr PR` matches a link. `show KEY` prints the work item with its links, pending confirmations, last report summary (untrusted) and the last 20 events. Human output of untrusted fields is sanitized (Output sanitizing).

Exit codes: `list` 0, 2; `show` 0, 2, 10 (the key has no work item), 21.

### stop

`stop KEY` ends ticket-work's activity on a ticket. It first adopts the agent when no id is stored (Agent adoption). It refuses (exit 20 `live`) while the agent is live or the job is `running`; nothing overrides `live` (stop the agent with `agent-spawn stop` first). Otherwise by phase: `pending` rejects the pending start (as `reject`: claim released plainly, phase `failed`); `applying` exits 20 `not_active` (the repair step handles it); `merged` with outstanding cleanup (`cleanup.claim` `held` or `cleanup.teardown` `pending` or `refused`) releases the claim plainly, sets `cleanup.claim: released`, clears the attention reasons `teardown_refused` and `rule_failed`, leaves `cleanup.teardown` as it is and exits 0 `changed`, and a `merged` item with no outstanding cleanup exits 20 `not_active`; `failed` clears every attention reason and sets phase `stopped` (exit 0 `changed`); `stopped` exits 0 `unchanged`; for `starting`, `working` and `in_review` it does these steps in order: (1) closes every open pending record of the item (Pending confirmations); (2) cancels a queued or held job (`jobsctl cancel <job id>`; plain cancel); (3) releases the claim with a plain `release` and sets `cleanup.claim: released`; (4) sets phase `stopped` and clears every attention reason the item holds except `teardown_refused`; (5) evaluates the event `stopped` once: the board's `stopped` rule, if any, follows the Confirmation matrix like every rule (a TTY dialog, `--yes`, or a pending `transition` record, exit 13), and its outcome never undoes the stop. After `stopped`, `sync` records pull request facts for display but makes no transition, comment or teardown for the item and renews no claim; the one exception is confirming the `transition` record of event `stopped`. The agent and the worktree stay parked; removing them is `agent-spawn teardown` (`--force` there is human-only).

`start KEY` on a `stopped` or `failed` item is a restart (Re-adopt and restart).

Exit codes: 0; 2; 10; 11 (a hook vetoed the `stopped` rule); 12 (a lower tool failed); 13 (the item is stopped and a `transition` record awaits); 20 (`live`, `not_active`); 21.

### link and unlink

`link` and `unlink` require a human actor (exit 2 `human_only`; advisory, like ticketctl's). Both are allowed in every phase except `pending` and `applying` (exit 20 `not_active`), both support `--dry-run`, and both are idempotent: a `link` of an already linked pull request, and an `unlink` of an unknown link, exit 0 with `changed: false`.

`link KEY PR` records a manual link (tier `manual`) after checking through forgectl `show` and `forgectl whoami` that the pull request is authored by the user's own account, lies in a repository the board maps, and is not already linked to another work item. Refusals (exit 20, reason `not_linkable`, `details.why`): `author_not_me`, `author_unknown`, `repo_not_mapped`, `linked_elsewhere`, `not_found`, `fork`. A candidate (tier `title`, or an ambiguous `branch` token) is promoted by `link`. A `link` of a pull request that does not target the base chain is allowed (a human decided); it counts and, once merged, lands. `link` adds the `pr=` label to the stored agent (PR linking), fires `post-link` and writes an audit record. `link` never posts a comment itself (so a manual link and the next `sync` cannot post twice).

`unlink KEY PR` removes the link, removes the `pr=` label, and marks the pull request `ignored` for this work item so discovery never links it again; an ignored pull request is removed from the counting set.

Exit codes: `link` 0, 2, 10, 12, 20, 21; `unlink` 0, 2, 10, 12, 21.

### pending, confirm and reject

Design guide §4.4 applies. `pending` lists unresolved pending confirmations (`--all` includes resolved and expired ones until pruned); a record past its expiry is listed as `expired`. `confirm ID` on a TTY shows the stored `details.changes` and asks (the answer is read from `/dev/tty`); `--yes` with a human actor skips the dialog (the dashboard route); without a TTY and without `--yes` it exits 2 `human_only`. This is advisory, like ticketctl's confirmation (Residual risks). `reject ID` needs a human actor with the same rule. The behavior of each pending action is in Pending confirmations. Exit codes of `pending`: 0, 2.

### cron

`cron install|uninstall` writes or removes a managed crontab block (design guide §4.3): first line `# ticket-work managed`, last line `# ticket-work managed end`, an explicit `PATH`, the `XDG_CONFIG_HOME` and `XDG_STATE_HOME` lines when set, and the optional user-owned env-file prefix. It installs `ticket-work sync --quiet --actor auto:cron` every `--sync-interval` (default `10m`). With `--with-start` it also installs `ticket-work start --auto --quiet --actor auto:cron --board <name>` every `--start-interval` (default `30m`), one entry per ticket-work board that has a `queue_board`, or a single entry without `--board` when no board has one; starting automatically is opt-in. `--sync-interval` and `--start-interval` accept only ticket-queue's closed set (`1m 2m 3m 4m 5m 6m 10m 12m 15m 20m 30m 1h 2h 3h 4h 6h 8h 12h 24h`); `cron install` rejects `%`, newline and whitespace in every value it writes (cron treats `%` as a newline). An end-less block is never replaced. Exit codes: 0, 2.

### export, prune and validate

`export` prints audit records as JSON lines (`--since`, `--after-seq`, `--to PATH`, as ticketctl); there is no log export. Exit codes 0, 2.

`prune` deletes finished work items (phase `merged`, `stopped` or `failed`) older than `retention.work` (default 90 days) with their links, events and resolved pending records, and expired pending records older than `retention.pending`; it never touches `audit.jsonl`. It skips a finished item whose `cleanup.teardown` is `pending` or `refused` or whose `cleanup.claim` is `held`, prints a warning `agent_left` (agent ids) for every deleted item whose stored agent is not torn down, and deletes prompt files older than a day. `prune --item KEY` deletes the one finished work item (phase `merged`, `stopped` or `failed`) with its links, events and resolved pending records regardless of age, when its cleanup is complete (`cleanup.teardown` `done` or `not_needed` and `cleanup.claim` `released`); otherwise it exits 20 `not_active` (`details.phase`, `details.cleanup`). `--item` and `--older-than` together exit 2 `invalid_combination`. A ticket reopened after a merge starts as a new work item after `prune --item KEY`. Exit codes 0, 2, and with `--item` also 10, 20 and 21.

`validate` checks the config and the sibling tools: each required tool is installed and at its minimum version, `ticketctl whoami --site <site>` works per configured site, every board has a `started.to`, a `started.from`, repository rules and a resolvable repository (`wtctl locate`), `<state dir>/jobs` exists or can be created (mode 0700), the work-id and site name limits hold, there is one board per site, `queue_board` is set where used, and names present in both `jobs.pass_env` and `agent.env_allowlist` are reported as notices (`pass_env_overlap`); the notice `pass_env_missing_tmux` is reported when `agent.mode` is `interactive` and `jobs.pass_env` lacks `TMUX`, and with `--probe` the notice `sprint_board_missing` when ticketctl reports `ambiguous_board` for a site whose board has no `sprint_board`. It runs `ticket-queue validate` and reports its problems as `warnings` (a failure unrelated to ticket-work's use does not fail `validate`). `--probe` also runs `forgectl whoami --host` for each host of a mapped repository. Exit codes 0 or 12 (problems listed in `details.problems`).

## Work item and phases

A work item's `phase` is derived at each `sync` from the other tools' facts and set by the commands; the store caches it for `list` and `show`.

| Phase | Meaning |
|---|---|
| `pending` | a pending start exists and nothing was applied to the ticket (a human or a hook still has to answer) |
| `applying` | a start, restart or confirmed start is being applied; `previous`, `intent`, the plan hashes and the step list are stored; the job is added at the end of this phase |
| `starting` | the start changes were applied (or there were none), the job exists (or a foreground run is recorded), and the agent has not started a run |
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
| `restore_failed` | the restore flow could not undo a step (detail: `status_moved`, `assignee_changed`, `sprints_changed`, `sprints_unrestorable`, `no_such_transition`, `sprint_closed` or `step_failed`) | the item is restarted, or stopped (a `failed` item is stopped by `stop`) |
| `pr_idle` | no activity on any open counting pull request for `sync.pr_idle_after` | activity is newer or no open counting pull request |
| `pr_closed_unmerged` | every counting linked pull request is closed and none merged | a counting pull request is open or merged again, or the item is stopped |
| `superseded` | a newer counting pull request replaces an older open or closed one (Stale and diverged work) | the pair no longer exists |
| `ticket_diverged` | the claim state shows someone else changed the ticket (Stale and diverged work), or a renewal was refused with `gone` or `hidden` | the item leaves the Active phases |
| `candidate_link` | a `candidate` link exists; the reason fires `post-attention` again for every added candidate `pr_id` (the one exception to "a change of detail does not fire") | no candidate remains (linked or ignored) |
| `teardown_refused` | teardown was refused (Teardown) | teardown is `done` |
| `agent_blocked` | the agent's attention is `blocked` or `escalated` | the agent is live again or its last outcome is `done` |
| `agent_failed` | the agent's attention is `failed`, `timeout`, `lost` or `unreported`, or the agent is `launch_failed` in `working` or `in_review`, or its artifact is invalid or missing (detail `artifact_invalid` or `artifact_missing`), or no pull request exists after `done` | a later run is live or `done` with a valid artifact |
| `job_held` | a held job with no agent report (launch escalation, manual hold) | the job is not held |
| `job_failed` | a terminal failed or canceled job while an agent ran (detail `job_missing` for a pruned job), or a veto of a resume | a new job is added (`resume`) or the item is stopped |
| `pending_expired` | a pending start expired | the item is restarted or stopped |
| `sync_failed` | a step failed for the item | the next `sync` handles the item without error |
| `sprint_failed` | the sprint write failed after the transition landed | the item reaches `merged` or is stopped |
| `claim_lost` | a lapsed claim could not be re-taken (Sync order, step Claims); Active phases only | the claim is held again |
| `agent_missing` | a stored agent id gives exit 10 with status `torn_down` or unknown while the item is Active, the agent is `session_missing`, or adoption found several candidates (detail `ambiguous`) | an agent is adopted or found |
| `rule_failed` | a status-map rule failed permanently, or a retry-on-change outcome of `pr_merged` (Events) | the event is re-evaluated and applied, declined or skipped, or the item is stopped |

Every reason added to the set fires `post-attention` once for that addition (a reason cleared and set again fires again); a reason that changes only its detail does not. The payload carries `reason` and `dedupe_key` (`<work id>:<reason>`).

### Phase scope

Every other text that says "Active phases" refers to this table.

| Set | Phases |
|---|---|
| Active | `pending`, `starting`, `working`, `in_review` |
| Transient | `applying` (owned by the command that is applying; `sync` touches it only in Expiry and Repair) |
| Finished | `merged`, `stopped`, `failed` |

| Sync step or rule | Covers |
|---|---|
| Expiry | items with open pending records |
| Repair | `applying` |
| Claims: renew and re-take | items with `cleanup.claim: held` in an Active phase, or in `merged` |
| Claims: release | items in `stopped` or `failed` with `cleanup.claim: held` (older than `claim.orphan_after`, lease not held); claims of this store whose item is missing or has `cleanup.claim: released` |
| Agents, Jobs | Active phases (Jobs: only with a stored job id or foreground marker) |
| Discovery, Read | Active phases, `merged` while cleanup is outstanding, and `stopped` (facts for display only) |
| Stale flags, `ticket_diverged` | Active phases |
| Rules | Active phases (the `stopped` event is evaluated by `stop` itself) |
| Cleanup | `merged` |

`cleanup.claim` (`held` or `released`) records whether ticket-work holds the claim, in every phase: it is set `held` in the same transaction that stores a start or restart and `released` after every release. Renewal and re-take apply exactly to items with `cleanup.claim: held` (Claims: renew and re-take); the orphan sweep releases a claim of this store whose item is missing or has `cleanup.claim: released`.

## Start order

0. **Resolve the key (only when `KEY` is given).** Apply the Lookup rule (Overview). Nothing is contacted except `ticketctl sites resolve`.
1. **Gate (`--auto` only).** `start --auto` requires jobsctl (`jobs.enabled: true`) and takes no `KEY` and no `--yes` (exit 2 `invalid_combination`). `capacity` is `effective_free` of `jobsctl capacity --queue <jobs.queue> --json`; `null` means unbounded. `pending_starts` is the number of open pending records of action `start`. If `capacity` is not `null` and `capacity - pending_starts <= 0` the command exits 22 `nothing_to_start` (`reason: no_capacity`); if `pending_starts >= start.max_pending` it exits 22 (`reason: pending_exists`). A human `start` has no gate; when `effective_free` is 0 or less the dialog shows "the job will wait in the queue" and the result carries the warning `queue_full`.
2. **Lookup, lease and claim.**
   - With `KEY`: take the ticket lease for the resolved work id (waiting at most 30 seconds, then exit 20 `busy`), look up the work item and refuse by phase before any claim is made: `pending` exits 20 `already_started` (`details.phase`, hint `confirm`); `applying` hint `sync`; `starting`, `working`, `in_review` hint `resume`; `merged` hint `stop` while cleanup is outstanding, else `prune --item <KEY>`. A `stopped` or `failed` item is a restart (Re-adopt and restart). Then read `ticket-queue claims --holder <holder> --site <site> --json`: an entry for the key whose `store` label is not this store's id exits 20 `foreign_claim` and releases nothing. Then `ticket-queue claim KEY --site <site> --holder <holder> --label store=<store id> [--ttl D]`.
   - Without `KEY`: `ticket-queue next --claim --holder <holder> --label store=<store id> [--board <queue_board>] [--ttl D]`; exit 22 from `next` is `nothing_to_start` (`reason: empty`). The key is known only now: take the ticket lease (30-second wait, else release plainly and exit 20 `busy`), look up the work item and apply the same phase refusals, now after the claim (Claim release rules: an item found after the claim).
   - A refusal (exit 20) of the claim is passed through (`reason` and `details.lower_error` from ticket-queue). A claim is local: it writes nothing to the ticket system. A result with `renewed: true` for a ticket with no work item and the `store` label of this store is an orphan claim of this store and is used as it is; with another store's label it exits 20 `foreign_claim` (`details.key`).
3. **Read.** `ticketctl get KEY --site <site> --fields key,status,type,labels,assignee,reporter,estimate,blocked,parent,epic,sprints,title,description,acceptance_criteria,links --json`. A key that moved is followed (`key` takes the canonical key, the typed key stays in `requested_keys`; the work id keeps the typed key). The live assignee is stored as `start_assignee` (account id or null); `previous.sprint_ids` come from `sprints` of state `active` or `future`.
4. **Resolve.** The board is the one board whose `site` equals the ticket's site. The repository and base come from the ordered rules (Ticket to repository and branch); a ticket matching no rule exits 20 `unmapped` (`details.why: no_rule`). `wtctl locate <repo-id> --json` is run for the repository (wtctl may auto-clone when its own `auto_clone` is on; that also applies to `--dry-run`); a repository wtctl cannot resolve exits 12 `repo_unresolved` before anything is changed (wtctl exits 10, 12, 20 and 21 all map to `repo_unresolved`, `details.lower_error`).
5. **Preconditions, trust and job pre-check.** Every rule of the board's `preconditions` is evaluated against the live ticket (Preconditions); a failure exits 20 `precondition_failed` (`details.rules`, `details.unknown`). `status_in` is redundant with `started.from` (step 6). A ticket whose prompt would exceed 1 MiB (title, description, acceptance criteria, and the other fenced fields, comments excluded) exits 20 `precondition_failed` with `details.rules: ["prompt_too_large"]`. An unattended start (Unattended runs) whose `reporter.account_id` is neither the user's own account id nor an element of `boards.<name>.trusted_authors` (exact comparison of `account_id`; a null `account_id` matches only `["*"]`) exits 20 `untrusted_reporter` (`details.reporter` is the account id). When jobs are enabled, `jobsctl add --dry-run` with the flags of step 11 runs: the warning `pass_env_undefined` exits 12 `lower_failed` (`details.cause: pass_env_undefined`); an existing job under the unique key whose labels lack `owner=ticket-work` or `ticket=<KEY>` or whose argv differs from the expected exits 20 `job_key_taken` (`details.job_id`); an existing job of ours exits 20 `already_started` (hint `sync`).
6. **Plan.** `ticketctl transition KEY --site <site> --to <started.to> [--assign me] --if-status <live status> --dry-run` (`--assign me` only when the rule has `assign: me`; `--resolution` only for a done target), then `ticketctl sprint add KEY --site <site> [--board <boards.<name>.sprint_board>] --sprint <started.sprint> --dry-run` when the rule names a sprint. The live status must be one of `started.from`, or equal to `started.to` on a restart; else exit 20 `precondition_failed` (`details.rules: ["started.from"]`, `details.current_status`). `previous` (`status`, `sprint_ids`), `intent` (`assign`: true when the plan changes the assignee from none to the account; `sprint_id`: the resolved sprint id or null) and the planned `changes` come from the dry-run output; nothing is stored yet. A plan in which every write is `unchanged` (or that has no write) is an empty plan.
7. **Hooks.** The `pre-enqueue` hooks run (payload `phase` is the work item's phase, or `null` and `object_id` the work id when no work item exists), then the `pre-transition` hooks of every planned write with that write's plan; a `pre-transition` hook runs again only when the plan hash changed. A veto exits 11. An escalation records a pending start (the plans, hashes and `details.changes` already exist) and exits 13.
8. **Confirm.** The Confirmation matrix. A decline exits 20 `declined`, stores nothing and releases the claim plainly (Claim release rules). A pending start stores the work item in phase `pending` with its identity, repository, branch, base, `start_assignee`, the `--skill/--mode/--sandbox` overrides, the `unattended` flag (true for `start --auto`), the plan hashes, the launch summary hash, `previous` and `intent`; the settings snapshot and the run token are created at step 9.
9. **Record intent (write-ahead).** One transaction stores (or updates from `pending`) the work item with phase `applying`, `cleanup.claim: held`, `previous`, `intent`, `started_status`, `start_assignee`, `run_started_at` (now), the plan hashes, the launch summary hash, the run token and the settings snapshot (Job command), the step list (one display entry per planned write, each `planned`) and, when the start came from a pending record, marks that record `confirmed`. An empty plan has no steps.
10. **Apply.** For each write: `ticketctl ... --site <site> --yes --expect-plan <hash> --actor <actor> [--decision-id ...]` (the `pre-transition` hooks already ran at step 7). The result is handled by Apply outcomes. After each write returns, its status (`applied`, `unchanged`, `skipped`, `failed`, `unknown`) is stored with the result in one transaction (display only; Restore reads the live ticket). `last_written_status` is set after each applied transition.
11. **Enqueue.** With jobsctl: holding the ticket lease, `jobsctl add --queue <jobs.queue> --unique-key ticket:<site>:<KEY> --max-retries 0 --timeout none --cwd <state dir>/jobs --kill-grace <jobs.kill_grace> --label ticket=<KEY> --label owner=ticket-work --pass-env <name>... [--env XDG_STATE_HOME=<value>] [--env XDG_CONFIG_HOME=<value>] --actor <actor> -- <executable> [--config <path>] _job <work id>`; the two `--env` entries are passed only when those variables are set. `<executable>` is the real path of the running ticket-work executable. `<state dir>/jobs` is created (mode 0700) before the first add. A result with `created: false` is accepted only for a job whose labels and argv are ours (stored, warning `existing_job`); otherwise exit 20 `job_key_taken`, restore flow if a write landed. Then, in one transaction: store the job id, set phase `starting`, record the event `started` (key: the first 16 hex of sha256 of the run token), release the lease. Without jobsctl (`jobs.enabled: false`, human actor): store phase `starting` with `job: {id: null, foreground: true, pid, pid_start}` and release the lease, then run the job command in the foreground of `start`; the exit code is the job's (Job command table) and the result prints `job: {id: null, foreground: true, exit_code}`. `start --auto` never runs without jobsctl, so cron never blocks for an agent's lifetime.
12. **Output.** The start result object. Exit 0 (or the foreground job's exit code).

A `--dry-run` start performs steps 0 to 6, reads and dry-runs only (including `wtctl locate` and `jobsctl add --dry-run`), runs no hook and no dialog, stores nothing, claims nothing (`ticket-queue claim --dry-run` or `next --claim --dry-run`) and takes no lease.

### Apply outcomes

Three result columns: the first write at `start` or `confirm`, a later write (`sprint add`), and a status-map rule (a `sync` or `confirm` write; also the `stopped` rule of `stop`).

| Result | First write at start | Later write (`sprint add`) | Status-map rule |
|---|---|---|---|
| exit 0 (`applied` or `unchanged`) | step recorded, continue | step recorded, continue | `applied` |
| exit 20 `stale_ticket` | re-plan once (step 6). A human at a TTY is asked again; otherwise nothing landed (see "Nothing landed") | the same re-plan; if it fails again `sprint_failed` | re-plan once; again: transient (`sync_failed`) |
| exit 12 `outcome_unknown` | step `unknown`; re-run the same command once with the same `--expect-plan` (a landed write is `unchanged`); still unknown: restore flow with a live read first, exit 12 | step `unknown`; re-run once; still unknown: `sprint_failed` | re-run once; still unknown: transient |
| exit 12 `partial` | restore flow, exit 12 | not applicable | transient (the rerun sees the assignment `unchanged`) |
| exit 13 `escalated` (ticketctl's own hook) | nothing landed: record a pending start (`escalated_by: ticketctl`), the item returns from `applying` to `pending` (steps cleared, claim held), exit 13; ticket-work never passes `--override-escalation` | `sprint_failed` (detail `escalated`) | a pending `transition` record (`escalated_by: ticketctl`) |
| exit 11 (ticketctl's own hook vetoed) | nothing landed: exit 11 | `sprint_failed` (detail `vetoed`) | `skipped` (`vetoed`) |
| exit 20 `precondition_failed` from `--if-status` | nothing landed: exit 20 with the lower reason | not applicable | `skipped` (`from_mismatch`) |
| exit 20 `no_such_transition`, `sprint_closed`; exit 21, 22; exit 12 `rejected`, `lookup_incomplete` | nothing landed: exit 20 or 12 with the lower reason | `sprint_failed` (detail the lower reason) | permanent: `failed`, attention `rule_failed` |
| any other exit 12 | nothing landed: exit 12 `lower_failed` | `sprint_failed` | transient: `sync_failed`, retried at the next `sync` |
| a failure after a first write landed that is not a sprint failure (a later `update`, a crash, `outcome_unknown` unresolved) | restore flow and release with `--failed` per Claim release rules | not applicable | not applicable |

**Nothing landed.** In every `start` or `confirm` row marked nothing landed, one transaction releases the claim per Claim release rules, sets phase `failed` with `restore_state: done` and records the error on the (already `confirmed`) pending record `details.apply_error`; the item is then restartable at once (a later `start KEY` is a restart). The repair step is only for crashes.

Hook outcomes for `pre-transition` and `pre-enqueue` are decided at step 7 (before the Confirm decision): a veto exits 11; an escalation records a pending start (`escalated_by: <hook>`) and exits 13. In `sync` (a status-map rule): a veto records the event `skipped` (reason `vetoed`); an escalation records a pending confirmation (`escalated_by` the hook). A veto or escalation of a later write during `confirm` is `sprint_failed` (detail `vetoed` or `escalated`). The `pre-transition` hooks run once with the plan before the decision and again only when the plan hash changed (a re-plan).

### Confirmation matrix

An ordered list; the first matching row decides, evaluated for each planned write set of one start or one rule.

1. The plan is empty (every write `unchanged`, or there is none): nothing is confirmed; continue at step 9.
2. Rule `confirm: never` (any event except `started`; for `started` it is a config error at load, `invalid_config`): the rule is not applied.
3. Rule `confirm: auto` (set only in config files, per board and event; `defaults.confirm` supplies it): applied without asking, any actor, including `start --auto` and `sync`.
4. Every `pre-transition` hook of the write set returned stdout JSON with `"enforced": true` and `"decision": "allow"` (design guide section 12): treated as row 3. Exit 0 without that JSON means only "do not block". These hooks ran at step 7 (Apply outcomes); the gate is therefore known before this decision.
5. `auto:` actor: never prompts; `--yes` with an `auto:` actor exits 2 `human_only`; the result is a pending record (row 8).
6. Human actor with `--yes` (any TTY state): the caller confirmed in its own dialog; no prompt; applied.
7. Human actor on a TTY without `--yes`: the dialog reads `/dev/tty`; it shows the key, the sanitized title, the reporter's display name together with the reporter account id and whether it is trusted, the repository, branch, base, mode, sandbox, setting sources, the queue warning when the queue is full, and the plans (status, assignee, sprint changes by name); one question; a no is `declined`. The dialog times out after 10 minutes (a no).
8. Otherwise (no TTY, no `--yes`): a pending record is created (`action: start`, `details.changes`), `post-pending` fires, exit 13, the claim stays held.

`confirm`'s dialog is the same as row 7 and is built after the live re-checks (Pending confirmations). `sync` applies the rows per due rule; a human `sync` at a TTY shows all due plans together and asks once.

### Claim release rules

| Outcome | Release |
|---|---|
| a human `start` refusal or lower failure before step 10; a decline; a hook veto; a rejected or expired pending start; a diverged ticket; a restart refusal | plain `release` (`ticket-queue release KEY --site <site> --holder <holder>`) |
| `start --auto`: a permanent refusal or failure after its claim and before step 10 (`precondition_failed`, `unmapped`, `untrusted_reporter`, `already_started`, `job_key_taken`, `repo_unresolved`, a hook veto, a lower failure that is not transient) | `release --failed`; the run then claims the next candidate, at most `start.scan_limit` claims per run (default 5), and still starts at most one ticket. When no candidate was started the run exits 22 `nothing_to_start` (`reason: scan_exhausted`, `details.refused`) |
| a transient failure at any point before step 10 (a lower failure whose retry class is transient or whose `details.retryable` is true, `busy`), human or `--auto` | plain `release`; an `--auto` run ends |
| a failure after a write landed (the restore flow) | `release --failed`, except plain when the lower error is transient or `details.retryable` is true, when a human canceled the job, or when the cause is ticket-work's own crash (the repair step) |
| a refusal for an item found after the claim (a keyless start): phase `stopped`, `failed` or `merged` | as the rows above (the claim is this call's) |
| a refusal for an item found after the claim in phase `pending`, `applying`, `starting`, `working` or `in_review` (`renewed: true`) | nothing: the claim belongs to the item and is never released by a refusal |

A refusal releases only the claim of this call or an orphan claim of this store (`renewed: true` with no work item); it never releases a claim of an active work item.

### Re-adopt and restart

`start KEY` on a `stopped` or `failed` item is a restart. It runs the full flow (steps 2 to 12) with these differences. (1) Step 6: `started.from` and the `status_in` precondition pass when the live status already equals `started.to`; `previous` and `intent` are recomputed from the live ticket (a restart after a `stopped` rule starts again from the status the rule set). (2) A stored agent id is kept; the job command resumes a parked agent instead of launching a second one (a stored agent that never ran is continued with `agent-spawn resume`). (3) Step 8 is skipped for an empty plan: nothing is confirmed, and the dialog is not shown (the usual start dialog is shown when the plan changes the ticket). (4) The attention reasons `restore_failed`, `pending_expired` and `job_failed` are cleared; `run_token`, `settings`, `run_started_at` and `restore_state` are reset. `start --auto` restarts a `failed` item and refuses a `stopped` one (`already_started`, release per Claim release rules). A headless restart re-runs the reporter rule (step 5). The `started` event fires again (key: the hash of the new run token); `pr_opened` and `pr_ready` do not (their keys are `once`).

A `merged` item is not restarted: `start KEY` exits 20 `already_started` (hint `prune --item <KEY>` when cleanup is complete, `stop` when it is outstanding). A ticket reopened after a merge starts as a new work item after `prune --item KEY`.

## Job command

`ticket-work _job WORK_ID` is what the jobsctl job runs; its output is not a contract. It is resume-aware: it reads `JOBSCTL_JOB_ID` and `JOBSCTL_ATTEMPT` but decides from its own records. The work item stores at Start order step 9 a `settings` snapshot: the resolved `mode`, `skill`, `sandbox`, `permission_profile`, `setting_sources`, `env_allowlist`, `plugin_dirs`, `model`, `timeout`, `unattended`, the `actor`, the `decision_ids` and the run token. `_job` uses the snapshot for every agent call and for the decision ids of every audit record of the job; writes of the job (restore, rules it triggers) use the actor `auto:ticket-work` and carry the starter as the decision id `start-by:<actor>` (the snapshot keeps `actor` as the starter). All other configuration is read from the config files at run time (`--config PATH` is forwarded in the job argv when the start used it; `TICKET_WORK_*` variables are not inherited by jobs, which is why only non-safety scalars can be set from the environment). `jobs.pass_env` names are available to the job for ticket-work's own tool calls only. `_job` takes the ticket lease only for its short sections (loading the item, storing the agent id and the result, the restore flow).

1. Wait for the ticket lease (at most 60 seconds, else exit 1 `lease_timeout`; the job ends failed and the Jobs step of `sync` handles it). Load the work item. The job is current iff `jobsctl show --unique-key ticket:<site>:<KEY> --json` returns a non-terminal job whose `id` equals `JOBSCTL_JOB_ID` and whose labels hold `owner=ticket-work`; otherwise exit 20 `not_current_job`. A foreground run (no `JOBSCTL_JOB_ID`) is current iff the stored foreground marker has this process's PID. A current job stores its id. Refuse (exit 20 `not_active`) when the phase is not `starting`, `working` or `in_review`.
2. Run the `pre-launch` hooks. A veto restores the start (when the agent never ran) and exits 11. An escalation records the attention `job_held` (detail `launch_escalated`), a pending confirmation of action `launch`, and exits 13 (the job is held with reason `exit_13`). For an unattended run (snapshot `unattended: true`) the reporter rule (Unattended runs (b)) is checked again with a live `ticketctl get KEY --site <site> --fields reporter --json`; a failure exits 20 `untrusted_reporter` and, when the agent state is `never_ran`, runs the restore flow.
3. Find the agent. A stored id is checked with `agent-spawn show`: `parked` continues at step 4 (resume); `live` or `launching` is waited on; exit 10 with `details.status: tearing_down` exits 20 `not_active` with the attention `job_failed` (detail `tearing_down`); exit 10 with `torn_down`, `session_missing` or an unknown id exits 20 `not_active` with the attention `agent_missing`; a second agent is never launched for an item that holds an agent id. Without a stored id, Agent adoption: `adopted` continues as above, `none` launches, `unknown` exits 12 `lower_failed` (`details.cause: adoption_unknown`) with no launch and no restore.
4. Launch. Without a parked agent: first `agent-spawn launch --dry-run --json` with the same flags; it must exit 0 with `agent_settings.kind == "implement"`, `reads_third_party == false`, `would_refuse == null` and an empty `warnings` (otherwise exit 12 `lower_failed` with `details.cause: kind_check`, restore flow). Then `agent-spawn launch --kind implement --mode <mode> --repo <repo> --branch <branch> --base <base> --worktree new --skill <skill> --plugin-dir <bundled plugin> [--plugin-dir <configured>...] --prompt-file <file> [--input-file <file>] --permission-profile <profile> --sandbox <level> --setting-sources <list> --env-allowlist-only <name>... [--model <m>] [--timeout <d>] --label ticket=<KEY> --label owner=ticket-work --label repo=<repo> --wait --result-file <file> --json`. A stored agent that is parked and never ran (status `launch_failed`, no run) is continued with `agent-spawn resume <agent_id> --mode <mode> --prompt-file <file> --wait ...` (agent-spawn re-runs the launch for an agent without a session). A parked agent that ran: `agent-spawn resume <agent_id> --mode <mode> [--prompt-file <file>] --wait --result-file <file> --json`. A live agent: `agent-spawn wait <agent_id>` (no signal is forwarded; `jobsctl cancel --force` reaches only an agent started by this job's launch). The prompt file is built here, at each launch or resume (Slot contract). Every `launch` and `resume` call carries `--timeout <agent.timeout>` when `agent.timeout` is set (default none: a headless implement run is then bounded by claude-session's own kind default, 60 minutes; set `agent.timeout` for longer runs), `--model <agent.model>` when set, and `--setting-sources` as the comma-joined list (an empty list is `""`); `jobsctl add` carries `--timeout none` so a queue timeout never kills an agent. A prompt larger than 1 MiB at launch exits 20 `precondition_failed` (`details.rules: ["prompt_too_large"]`), restore flow when the agent state is `never_ran`. The answer stored by `resume --prompt-file` is written into the fenced prompt file here and cleared from the store when the call returns.
5. Classify by the JSON root (`error` or `agent`), the `phase` and the exit code with the ordered table below (the first matching row wins). The agent id from the result is stored at once; so are the report and the validated artifact fields (Slot contract).
6. Exit with the table's job exit.

| # | agent-spawn outcome | job exit | work item effect |
|---|---|---|---|
| 1 | exit 0, `done`, valid artifact (Slot contract, Artifact) | 0 | clear agent attention; phase from the next `sync` |
| 2 | exit 0, `done`, missing or invalid artifact (schema, ticket, `skill_marker`, `run_token`, `report.implicit: true`) | 18 | attention `agent_failed` (detail `artifact_invalid` or `artifact_missing`), event `agent_failed` key `<agent id>:<run>`; no restore |
| 3 | exit 13 with `phase: launch` (launch escalated) | 13 | pending `launch` record, attention `job_held` (detail `launch_escalated`) |
| 4 | exit 13 otherwise (`report.status` blocked or needs-input) | 13 | job held (`exit_13`); attention `agent_blocked`, event `agent_blocked`; `job_held` is not set for this pair |
| 5 | exit 11 (`vetoed` launch) | 11 | restore when the agent state is `never_ran`; `post-start-failed` |
| 6 | exit 14 unreported, 16 timeout, 17 lost, 18 failed | the same | no restore; attention `agent_failed` (detail the outcome), event `agent_failed` |
| 7 | exit 15 killed | 15 | no attention and no event; `job_failed` when the job ends non-canceled |
| 8 | exit 130 or 143 | the same | agent parked; attention `job_failed` when the job ends non-canceled |
| 9 | exit 20 with reason `third_party_*`, `tearing_down` or `live` | 20 | no restore; attention `job_failed` (detail the reason) |
| 10 | any other exit or error envelope when no run started (`phase: launch`, no run in the result) | the lower exit (12 when none) | restore when the agent state is `never_ran`; plain release when `details.retryable` is true; the agent id is kept |
| 11 | any other exit or envelope after a run started | the lower exit (12 when none) | no restore; attention `job_failed` |
| 12 | output that is not valid JSON | 12 | treated as row 11 when adoption finds an agent run, else as row 10 |

The job command never passes `--yes`, `--force` or `--override-escalation` to any tool. A `pre-launch` veto when an agent already exists (a resume) exits 11 with nothing restored; the item keeps its phase and gets the attention `job_failed` (detail `vetoed`); `resume` creates a new job.

Held jobs and `sync`: `job_held` is raised only for a held job that has no agent report (a `launch` escalation or a manual hold); a held `exit_13` job whose agent reported blocked or needs-input shows `agent_blocked` only; a held job whose agent has since started again (a human resumed it with agent-spawn) is resolved with `jobsctl resolve <id> --as done`; the agent then runs outside any job and its slot is no longer counted, which is accepted and recorded in Residual risks.

## Agent adoption

A work item without a stored agent id adopts one with this procedure, run by `_job` (step 3), by `sync` (step Agents), by `stop` and by `resume`, and it returns one of three results. For each key in `key` and `requested_keys`: with a stored job id first `agent-spawn list --label ticket=<KEY> --label owner=ticket-work --label job=<job id> --json`, and when that returns no accepted candidate the same query without the `job=` label (agent-spawn adds `job=` from `JOBSCTL_JOB_ID`; a foreground run has none). A candidate is accepted only when its `kind` is `implement`, its `repo` equals the work item's repository, its `created` is not earlier than the work item's `run_started_at` (reset at each start, restart and resume), and the worktree record named by its `worktree.record_id` (`wtctl show <record_id> --json`, read at most once per record per run) has `branch` equal to the recorded branch.

Result `adopted <id>`: exactly one accepted candidate; its id is stored. Result `none`: every query succeeded, wtctl was readable for every candidate that passed the cheap checks, and no candidate was accepted. Result `unknown`: `agent-spawn list` or a `wtctl show` failed, or several candidates were accepted (the last also sets the attention `agent_missing`, detail `ambiguous`); nothing is adopted, no restore and no `pr_merged` may rely on the absence of an agent, and the next `sync` retries. A stored id is never replaced by a label match. Labels only find candidates; stop, teardown, events and the restore act only on the stored id. `sync` runs adoption for items in `starting`, `working` and `in_review` without a stored id, and skips an item in `starting` whose job is `queued`.

## Sync order

1. **Lease.** Take the sync lease; a held lease sets `sync_rerun` and exits 0 `already_running` (Concurrency). A run that ends with `sync_rerun` set runs steps 2 to 12 once more.
2. **Expiry.** An open pending record past its expiry becomes `expired` (audit `pending_expire`). An expired `start` pending releases the claim plainly, sets the item to phase `failed` (`restore_state: done`) and sets the attention `pending_expired`; an expired `launch` pending cancels its job and restores when the agent state is `never_ran` (Restore); an expired `transition` or `comment` pending only drops the record (the next `sync` creates it again while the event still holds). Prompt files older than one day are deleted.
3. **Repair.** A work item in phase `applying` whose ticket lease is not held and whose `updated` is older than `claim.orphan_after` runs the restore flow (Restore; with the cause recorded as ticket-work's own crash, so the claim is released plainly). Every other phase is outside this step.
4. **Claims.** `ticket-queue claims --holder <holder> --json` gives each claim's `ticket_state` and `ticket.status`. For every item with `cleanup.claim: held` in an Active phase or in `merged` (Phase scope), the claim is renewed (`claim KEY --site <site> --renew --holder <holder>`) when the remaining life is below `claim.renew_below` of the TTL; an item with no entry in `claims` (the claim lapsed) goes to the re-take path at once. A claim state `moved` is renewed with the canonical key and the item updated. A refusal `not_held` or a missing entry first tries `claim KEY --site <site> --holder <holder> --label store=<store id>`; only when that is refused (`claimed` by another holder, `done`, `gone`, `skipped`, `hidden`) is, for an Active item, the attention `claim_lost` set (detail the lower reason; a re-held claim clears it) and, for a `merged` item, `cleanup.claim` set to `released` with no attention (cleanup goes on without the claim). A renewal refused with `gone` or `hidden` sets `ticket_diverged` (detail the reason) and releases as in Stale and diverged work. Entries with `hidden: true` carry no `ticket_state` and are renewed like any other. Items in `stopped` or `failed` with `cleanup.claim: held` for longer than `claim.orphan_after` (ticket lease not held) release their claim plainly and set `released`. A claim of this store (label `store=<store id>`) whose work item is missing or has `cleanup.claim: released`, older than `claim.orphan_after`, whose ticket lease is not held, is released plainly. The claim states are as fresh as ticket-queue's last `refresh`; schedule `ticket-queue refresh` in cron (Dependencies).
5. **Agents.** For every item in an Active phase without a stored agent id run Agent adoption. `agent-spawn show <id> --json` for each stored id (no `list`) updates the item's agent facts (status, `needs_attention`, last outcome); an agent whose last outcome is `done` and whose `last_artifact` is null is validated (Slot contract, Artifact). A stored id that gives exit 10 with `details.status: torn_down` or an unknown id sets the attention `agent_missing` only while the item is in an Active phase; for a `merged` item `torn_down` counts as teardown done (Teardown). The agent attention values map as follows: `blocked` and `escalated` raise the event `agent_blocked`; `failed`, `timeout`, `lost` and `unreported` raise `agent_failed`; `launch_failed` raises `agent_failed` (detail `launch_failed`) when the item is `working` or `in_review` (during `starting` the job table decides); `session_missing` sets `agent_missing` (detail `session_missing`).
6. **Jobs.** For an item in phase `starting`, `working` or `in_review` with a stored job id or foreground marker: read the stored job by id (`jobsctl show <job id> --json`); a foreground marker is read by checking that the PID is alive with the same start time (alive: a running job; dead: a terminal failed job). A stored id that gives exit 10 (a pruned job) counts as a terminal failed job with attention `job_failed` (detail `job_missing`). A terminal canceled, vetoed or failed job restores the start only when the agent state is `never_ran` (Restore); with an agent that ran, or an agent state `unknown`, it sets the attention `job_failed`. A held job: Job command. A sync never adopts a job by unique key.
7. **Discovery.** Discovery and read, below.
8. **Read.** Discovery and read, below.
9. **Stale flags.** `pr_idle`, `superseded`, `pr_closed_unmerged` and `ticket_diverged` are judged here, after Read, for items in an Active phase (Stale and diverged work).
10. **Rules.** For each item with a due event that has a rule, read the live ticket once: `ticketctl get KEY --site <site> --fields status,assignee --json` (up to 50 keys of one site per call); a failure is transient (`sync_failed`). Each event that is new or due for re-evaluation (Events) is evaluated against the board's status map: applied, recorded as a pending confirmation, or skipped.
11. **Cleanup.** After `pr_merged`: teardown (Teardown), then release the claim plainly and set `cleanup.claim: released`.
12. **Attention and hooks.** Attention reasons are set and cleared by the Attention reasons table; hooks are fired and the outbox is delivered (Hooks).

Every lower call has a timeout, `sync.call_timeout` (default 120 seconds); on expiry ticket-work stops the exact child process it started and the call fails as transient. Each step records its own failure per work item (attention `sync_failed` with the step and lower code) and continues with the other items; a failure of a lower tool for the whole run exits 12 `lower_failed`, a failure for part of it exits 12 `partial_results`.

### Discovery and read

**Discovery.** The repositories discovered are those named by a rule of every board that has a work item in a phase covered by Discovery in Phase scope. For each: `forgectl --json prs --repo <repo id> --author me --state all --updated-since <cursor minus sync.overlap> --limit 1000`. When a board names more than 5 repositories on one host, one host-wide call (`--host <h> --author me`) replaces the per-repository calls and its items are filtered to the mapped repositories. The cursor is the newest `updated_at` seen per repository; a repository with no cursor starts at the oldest `created` among the active items of its boards. Only a full `sync` stores cursors. A result with `complete: false` is re-run once split by `--state` (open, closed, merged); if one is still incomplete the item gets `sync_failed` (detail `incomplete`). An empty list is never evidence that a pull request is absent (PR linking). A repository whose `prs` call failed keeps its old cursor; only repositories whose calls completed advance.

**Read.** `forgectl --json show <pr>` for every linked, non-ignored pull request whose list item changed, and for every open one at least every `sync.reread_open_after` (default one hour). `show` takes the stored display `pr`; exit 10 marks the link `missing` and, in the same run, triggers one host-wide `prs --author me --host <h> --updated-since <cursor minus overlap>` whose items are matched by `repo_id`/`pr_id`: a pull request found under the same `pr_id` with another `repo` (a rename or a move) updates the stored `pr` and `repo` and restores the link. Facts are compared with the stored facts to derive events.

**Artifact claims.** For each url in `last_artifact.prs` with `verdict: unverified`: parse the url; if its host is not a host of a repository the board maps, record `verdict: rejected` (`why: repo_not_mapped`) without calling forgectl; otherwise `forgectl --json show <url>` once and apply the `claimed` tier: a confirmed pull request becomes a link and the entry `{pr_id, verdict: linked}`; one that fails the tier checks becomes `verdict: rejected` with the `not_linkable` `why`. A rejected claim never blocks the agent condition (it is shown in `show` as `rejected_claims`; a human resolves it with `link`).

**Authorship.** Membership in a `--author me` listing never proves authorship: every link is verified by `show`, and the author is compared with the login that `forgectl whoami --host <h>` returns for the pull request's host (called once per host per run, cached for the run). A host whose login cannot be resolved makes the pull request not linkable (`why: author_unknown`) and `validate --probe` reports it.

**Idle signal.** Link facts are `state`, `draft`, `head_sha`, `head_ref`, `base_ref`, `is_fork`, `merged_head_sha`, `updated_at` and `activity_at`. `activity_at` is `updated_at` unless it is older than `sync.pr_idle_after`; then (for open counting pull requests only) one `forgectl --json snapshot <pr> --no-bodies` per run supplies the newest of `head.pushed_at`, `reviews[].submitted_at` and `ci.checks[].finished_at` (null values ignored) and `activity_at` is the newer of that and `updated_at` (minimum forgectl version 0.52.0 covers `snapshot --no-bodies`).

## Status map

The map is per board, keyed by event name. Every event may have one rule; an event without a rule fires its hooks and does nothing else.

### Events

| Event | Fires when | Event key |
|---|---|---|
| `started` | the start changes were applied (or there were none), once per start attempt | the first 16 hex of sha256 of the run token |
| `pr_opened` | a counting linked pull request is first observed, in any state, once per work item | `once` |
| `pr_ready` | a counting linked pull request is first observed not a draft (open or merged), once per work item | `once` |
| `pr_merged` | at least one counting pull request merged and landed (PR linking), none counting is open, and the agent condition holds | first 16 hex of sha256 of the sorted merged `pr_id` values joined by `,` |
| `pr_closed_unmerged` | every counting linked pull request is closed and none merged | the same hash over the sorted `pr_id` set |
| `agent_blocked` | the agent's attention is `blocked` or `escalated` | `<agent id>:<run>` |
| `agent_failed` | the agent's attention is `failed`, `timeout`, `lost` or `unreported`, or its artifact is invalid or missing | `<agent id>:<run>` |
| `stopped` | `stop` ran | `once` |

`pr_merged` requires at least one landed merged pull request, no open counting pull request and the agent condition: the agent is torn down; or no agent is stored and Agent adoption returned `none` and no job is non-terminal; or the agent is not live, its last outcome is `done` with a valid stored artifact, and every entry of `last_artifact.prs` has `verdict: linked` with a link that is not open, or `rejected`, or the link is `ignored`. A stored job that is not terminal, the attention `agent_missing`, or an adoption result `unknown` makes the condition fail. When the condition fails, `post-status` fires with `event: pr_merged_partial` (reason `agent_unfinished`) and no rule applies; a merge while other counting pull requests are open fires it with reason `others_open`; a merged pull request that did not land fires it with reason `not_landed`. It fires once per change of reason, and `show` prints the current reason as `merge_wait` (null when none). Phase `merged` is the state in which the `pr_merged` condition holds, whatever the outcome of its rule.

An event is identified by `(work id, event, event key)`. Outcomes: `applied` (ticketctl applied or answered `unchanged`; a rule whose `to` equals the live status is `applied` whatever its `from`), `pending`, `declined` (a rejected pending record), `skipped` (reason `no_rule`, `never`, `caught_up`, `from_mismatch`, `vetoed`, `item_diverged`) and `failed`. Final outcomes: `applied`, `declined`, and `skipped` with reason `no_rule`, `never`, `caught_up` or `item_diverged`. Retry-on-change outcomes: `skipped` with reason `from_mismatch` or `vetoed`, and `failed`; they are re-evaluated only when the rule text changed (a stored rule hash) or the live ticket status differs from the status seen at the last evaluation (`seen_status`); `post-status` fires for such a re-evaluation only when the outcome changed. A retry-on-change outcome of `pr_merged` also sets the attention `rule_failed` (detail `{event, reason}`: `from_mismatch`, `vetoed` or the lower code) and gates cleanup (Teardown); for other events `failed` sets `rule_failed` and a `skipped` outcome only fires `post-status`. An open `pending` record is final for its event while it is open; an expired one drops the record and the next `sync` creates it again; a rejected one marks the key `declined`.

Catch-up. The pull request events due in one evaluation are ordered `pr_opened`, `pr_ready`, then `pr_merged` or `pr_closed_unmerged`. The latest due event that has a rule (not `confirm: never`) is applied; every due event before it is recorded `skipped` (`caught_up`) and every due event after it (it has no rule) `skipped` (`no_rule`). The `from` guard of the applied rule passes when the live status is in its `from`, or when walking back through the caught-up rules (latest first) reaches it: start with the set F of the rule's `from`; for each caught-up event with a rule whose `to` is in F, add that rule's `from` to F; the guard passes when the live status is in F. So `pr_opened: {to: In Review, from: [In Progress]}` and `pr_merged: {to: Done, from: [In Review]}` move an In Progress ticket to Done when the pull request opened and merged between two syncs. A board whose `pr_merged.from` names a status that no earlier rule produces will skip with `from_mismatch` and show `rule_failed`.

A newer pull request event of the work item supersedes open `transition` and `comment` pendings of earlier pull request events (Pending confirmations).

The outcome of a status-map write is given by the Status-map rule column of Apply outcomes.

### Rule fields

| Field | Meaning |
|---|---|
| `to` | target status name (required; ticketctl chooses the transition by target) |
| `from` | list of status names the ticket must be in; required for `started`; for other events absent means no guard. The live status is checked by ticket-work and passed to ticketctl as `--if-status <live status>` |
| `resolution` | required when the target is a done status. ticket-work cannot know status categories at load, so a missing resolution is found by the plan (ticketctl exit 22 `missing_required_fields` or `invalid_value`) and is a permanent failure (Apply outcomes) |
| `assign` | `me` only (any rule): assigns when the ticket is unassigned (ticketctl `--assign me`; an assigned ticket gives the plan warning `assign_skipped`, which is recorded and is not an error); `none` and account ids are a config error (`invalid_config`) |
| `sprint` | `open`, `next` or a numeric sprint id (`started` only) |
| `confirm` | `ask` (default), `auto` or `never` (Confirmation matrix) |
| `comment` | `true` posts one fixed-text comment per event (Ticket comments) |

`confirm: auto` applies without asking; it is set only in config files, never by a flag or an environment variable, per board and event, and `defaults.confirm` sets the default for rules that give none. `confirm: never` turns the rule off. Each applied rule writes the transition through ticketctl (plan with `--site <site> --dry-run`, `--yes --expect-plan <hash>` after the confirmation, `--actor`, `--decision-id`) and an audit record.

A board without `started.to` or `started.from` refuses `start` and fails `validate`. ticket-work ships no status names; `config.example.yaml` documents the shape with placeholder names.

### Ticket comments

`comment: true` on a rule (or `link_comment: true` on a board, which applies to the event `pr_opened` evaluated at `sync`; `ticket-work link` never posts a comment itself) posts one comment through `ticketctl comment KEY --site <site> --body-file <file> --dedupe-key <key> --yes --expect-plan <hash>`. The dedupe key is `ticket-work:` followed by the first 32 hex characters of sha256 of `<site>:<KEY>:<event>:<event key>`; this matches ticketctl's grammar and is at most 44 characters. The body is fixed text built from trusted data only (the event name and the pull request URL), followed by ticketctl's attribution paragraph for automatic actors. It follows the rule's `confirm` flow like a transition. After `outcome_unknown` it is retried with the same key; `lookup_incomplete` (only a human may post without a key) is a permanent failure. Comments are off by default.

## Stale and diverged work

- `pr_idle`: no activity on any open counting linked pull request for `sync.pr_idle_after` (default 14 days); activity is `activity_at` (Discovery and read). Cleared when activity is newer or no counting pull request is open.
- `pr_closed_unmerged`: every counting linked pull request is closed and none merged. The default is to notify only: the event has no rule, `post-status` fires with outcome `skipped` (reason `no_rule`) and the attention `pr_closed_unmerged` is set; no transition and no teardown.
- `superseded`: a counting linked pull request exists that has the same repository and the same `base_ref` as an older counting pull request of the work item that is open or closed unmerged. Stacked pull requests (different base chain) and pull requests of different repositories never match. Cleared when no such pair exists.
- `ticket_diverged`: someone else changed the ticket. Judged in Sync order step 9, after Read, for items in an Active phase only. It is set when the claim state is `gone`; or `reassigned` while the work item's `start_assignee` is null or the account (a ticket that a colleague held at start is never judged reassigned); or `done` while the claim entry's `ticket.status` differs from `last_written_status` (the status ticket-work itself last wrote, so its own moves never count), the item has no counting merged pull request in the facts just read, and no rule of the board is still due. `assign` is restricted to `me`. The automatic actions are: release the claim plainly once and set `cleanup.claim: released` (the item is excluded from renewal and re-take), and apply no ticket-write rule to the item from then on (outcome `skipped`, reason `item_diverged`); `sync` keeps reading pull request facts, raises hooks, and tears down after a merge. A `moved` claim is renewed with the new key. The attention clears when the item leaves the Active phases (`merged`, `stopped`, `failed`) and is never set for them.

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

- **Boards.** A site has exactly one board: a configuration with two boards naming the same `site` is refused at load (exit 2 `invalid_config`). `boards.<name>.queue_board` (optional) is the ticket-queue board whose tickets this board takes. `boards.<name>.sprint_board` (optional) is the board passed to `ticketctl sprint add --board`; it is needed when the site has several boards. `--board B` on `start` and `list` always names a ticket-work board.
- **Rules.** `boards.<name>.repos` is an ordered list of rules `{match: {label, project, epic, issue_type}, repo: <repo id>, base: <branch>}`; the first match wins and a rule with an empty `match` is the board default. `match` keys are all optional and ANDed, each a single string: `label` (equals one of the ticket's labels, case-insensitive), `project` (the key prefix before the first `-`, case-insensitive), `epic` (the epic's key, exact), `issue_type` (`type.name`, case-insensitive). `component` is not a match key (ticketctl has no component property). A ticket that matches nothing is refused with `unmapped`. A `repos.<id>` override entry (per-repository settings) takes the per-repository position in the precedence order.
- **Branch.** The branch is `<type>/<KEY>-<slug>`. `type` comes from `boards.<name>.branch.types` by issue type (default `feat`). The slug is derived from the title by one rule: NFKD-normalized, ASCII only, lower-case; runs of characters outside `a-z0-9` become one `-`; the result is split on `-`; every all-digit token is dropped together with the token before it; the tokens are kept whole and added while the joined string stays within 40 characters (a first token longer than 40 is cut to 40); the result is trimmed of `-`; `ticket` when empty. No other ticket text reaches the branch and no other ticket's key can appear in it. Examples: `Follow up to PROJ-1 regression` gives `follow-up-to-regression`; `Fix PROJ-10 and PROJ-1` gives `fix-and`; a full-width `ＰＲＯＪ－１ fullwidth key` gives `fullwidth-key`; 33 letters `a` followed by ` PROJ-12abc` give the 33 letters, `-` and `proj` (the whole-token rule never cuts the result into `proj-1`, which the old 40-character cut did). The slug is lossy by design (`Fix 404 page` gives `page`): the all-digit token and the token before it are dropped so no key-like pair can appear. ticket-work passes `--branch` and `--base` to agent-spawn. The key always appears as a whole token behind `<type>/`.

## PR linking

Every link has a `tier`; linking never relies on the agent's claim alone.

A linked pull request **counts** (for the events, `pr_idle`, `superseded` and the teardown selection) when it is not from a fork (`is_fork` false) and its base chain ends at the work item's `base`: its `base_ref` equals the recorded `base`, or equals the `head_ref` of another counting linked pull request of the work item (checked iteratively). Pull requests linked by the manual tier count regardless of the chain. A linked pull request that does not count is shown (`counts: false`) and drives nothing. A **landed** merged pull request is one that reached the base: its `base_ref` equals the recorded `base`, or equals the `head_ref` of another counting linked pull request of the work item that is itself merged and landed (checked iteratively, merged pull requests only); a merged manual link is landed. `landed` drives `pr_merged` and the teardown selection; `counts` drives display, `pr_idle`, `superseded`, the phase and the other events.

| Tier | Evidence | Effect |
|---|---|---|
| `claimed` | the agent's artifact `prs[].url` names a pull request that forgectl `show` confirms (the url host must be a host of a mapped repository, checked before any call, Discovery and read): authored by the user's account, in the work item's repository, with the head branch ticket-work launched (exact `head.ref` equality with the recorded branch), `is_fork` false, and the base chain of the counting rule | linked automatically |
| `branch` | `head.ref` equals the recorded branch of a work item (exact, checked first, the pull request belongs to that work item only), or contains the whole-token key of exactly one active work item (case-insensitive, any key of the item's `key` and `requested_keys`, never a generic pattern) for a pull request authored by the user in the work item's repository, not a fork, whose base chain ends at the work item's base. A token that matches the keys of two or more active work items makes the pull request a `candidate` for none of them linked automatically (state `candidate`, attention `candidate_link` on each) | linked automatically |
| `title` | the key only in the title | recorded as `candidate`; fires `post-attention` (`candidate_link`); never moves the ticket until `link` |
| `manual` | `ticket-work link` | linked |

- The key matches `head.ref` with `(?<![A-Za-z0-9])KEY(?![A-Za-z0-9])` (case-insensitive, `KEY` escaped).
- Candidates are re-evaluated at every `sync` (a candidate becomes a link when the evidence becomes unambiguous, for example after the base chain resolves); `candidate_link` is set once per candidate `pr_id`.
- A link stores `pr_id` and `repo_id` (forgectl's opaque ids) and the display `pr` and `repo` (host/path) refreshed at every `show`; the board's repository rules are compared with the display `repo`, the stored `repo_id` follows a rename. A link also stores the tier, the time and the last-seen facts (`state`, `draft`, `head_sha`, `head_ref`, `base_ref`, `is_fork`, `merged_head_sha`, `updated_at`, `activity_at`).
- A link's `pr=` label (the pull request's forgectl `pr` field, not the user's typed form) is added to the work item's stored agent at link time (`agent-spawn label add <agent_id> pr=<pr>`); when no agent is stored or it is torn down (exit 10) the label is skipped (warning `label_skipped`) and `sync` adds it later when an agent exists (`label_synced` on the link). Labels are a multiset: adding the same pair is a no-op and nothing has to be replaced. ticket-work never reads labels as evidence; `pr=` exists for review-respond's lookup, which sees it only after the first `sync` that links the pull request (a bounded delay; the agent's own optional self-label closes it sooner). The `pr=` label is never linking evidence.
- One ticket may have several links (stacked pull requests, follow-ups). A work item is one repository: the automatic tiers (`claimed`, `branch`) link only pull requests whose repository is the work item's; a pull request in another mapped repository is linked by `link` (manual, counts and lands regardless of the chain).
- The `branch` and `title` tiers link a pull request only if it was created at or after the work item's `created` time; an older one is a `candidate` (a human `link` promotes it). `claimed` is exempt.
- A pull request linked to one work item is never linked to another automatically (`linked_elsewhere`).
- `prs --repo` for a missing or renamed repository returns exit 0, an empty list and `complete: true`; `show` returns exit 10. An empty list is never read as "no pull requests": a link is marked `missing` only by a `show` exit 10.
- Discovery uses the cheap `prs` list; `merged_head_sha`, `merged_at` and `closed_at` need one `show`.

## Pending confirmations

A pending record has `id` (`^pd-[a-z2-7]{8}$`), `tool: ticket-work`, `action`, `target` (the work id), `created`, `summary`, `expires`, `actor`, `plan_sha256` (map of step to hash), `launch_sha256` (string or null: the launch summary hash), `rule`, `event`, `escalated_by`, `status` (`open`, `confirmed`, `rejected`, `expired`) and `details`. `action` is `start`, `transition`, `comment` or `launch`. Records never contain ticket text. `details.changes` is an array of `{step, field, from, to}` (status names, `me` or account ids, sprint ids; host text capped at 64 characters and sanitized); a `start` pending also holds `details.plans`, `overrides`, `unattended`, `previous` and `intent`. Expiry is performed by `sync` (Sync order step 2); `pending` also treats a record past its expiry as `expired` when it lists. `declined` is the answer no at ticket-work's own dialog; it is never stored as pending.

- **`confirm ID` procedure (every action).** 1. State: a record that is not `open` exits 20 `not_pending`; an expired one exits 20 `expired` (the claim was already released by `sync`, or is released by this call when no `sync` ran); a `start` record needs the item in phase `pending`, a `transition` or `comment` record needs an active item (or, for event `stopped`, a `stopped` item), a `launch` record needs the item in `starting`; otherwise exit 20 `not_pending`. 2. Live re-checks of a `start` record, in this order, by re-running Start order steps 3 to 5 (the read, repository and trust rules) with live data, then the claim (a refused renewal tries a new `claim`; a refusal is exit 20 `claim_lost`), then the other `pre-` hooks (the hook named in `escalated_by` is skipped in this invocation). A permanent refusal (exit 20: `precondition_failed`, `unmapped`, `untrusted_reporter`, `claim_lost`) rejects the record (`details.rejected_by: confirm_recheck`), sets the item to phase `failed` with `restore_state: done` and releases the claim plainly; a transient lower failure (exit 12), a hook veto (exit 11) or an escalation (exit 13) leaves the record `open`, the item and the claim as they are, and returns that exit. 3. Re-plan with `--dry-run`. 4. If every re-planned step is `unchanged` and the launch summary hash is equal, the record is `confirmed` with nothing to apply (for a `start` record the stored `previous` and `intent` are kept and the flow continues at Start order step 9, which skips the writes). 5. Otherwise, if any step hash differs from the stored `plan_sha256` or the launch summary hash differs from `launch_sha256`, the old record becomes `rejected` (`details.superseded_by`), a new pending record is created and the command exits 13 (`stale_plan`). 6. Otherwise the dialog (Confirmation matrix row 7, built from the live data of step 2) or `--yes` applies and the flow continues at step 9 (the record is marked `confirmed` in that transaction). Writes made by `confirm` use the confirmer's actor and `--yes` (the original starter stays in the snapshot `actor` and in the decision id `start-by:<actor>`).
- `start` pending: created by a non-TTY start, a hook escalation at step 7 or ticketctl's own escalation at the first write; the item phase is `pending` (a ticketctl escalation moves the item from `applying` back to `pending`). It holds the claim (renewed by `sync`). `pending.start_expiry` defaults to 24 hours. The `unattended` flag of the snapshot comes from the original start (`details.unattended`), never from the confirmer. A ticketctl escalation is never overridden by ticket-work: `confirm` applies again, ticketctl escalates again, the command exits 13 with the record left open and `details.hint` telling the human to complete the ticket change with ticketctl (`--override-escalation`) and run `confirm` again, which then sees an empty plan. `reject`, expiry and a diverged ticket release the claim plainly; a rejected or expired pending start sets the item to phase `failed` with `restore_state: done`; a later `start KEY` is a restart.
- `transition` and `comment` pending: created by a non-TTY `sync` or by `stop` for a rule whose `confirm` is `ask`, keyed by work id, event and the event key so a repeated `sync` never duplicates it. `confirm` follows the procedure (steps 1, 3 to 6; a ticketctl escalation is handled as above). Expires after `pending.expiry` (default 7 days); expiry drops the record only. When a newer pull request event of the item is evaluated (applied or recorded pending), every open `transition` or `comment` record of an earlier pull request event becomes `rejected` (`details.superseded_by_event`).
- `launch` pending: created when a `pre-launch` hook escalated in the job. `resume` is refused (exit 20 `not_active`, hint `confirm`) while it is open. `confirm` re-runs the other `pre-` hooks and continues the held job with `jobsctl retry <id> --attempt N` (N is `attempt` from `jobsctl show`). `reject` and expiry cancel the job (`jobsctl cancel <id>`), then run the restore flow when the agent state is `never_ran`; if the agent ran they only cancel the job and clear `job_held`.
- `stop` closes every open record of the item except a `transition` record of event `stopped` (they become `rejected`, `details.reason: stopped`).
- `confirm` and `reject` exit codes: 0; 2 `human_only`; 10 no such record; 11 a hook vetoed; 12 a lower tool failed; 13 a hook or ticketctl escalated again, or a stale plan created a new record; 20 `expired`, `not_pending`, `claim_lost`, `precondition_failed`, `unmapped`, `untrusted_reporter`.

## Restore

The restore flow undoes a start whose agent never ran. It runs from `start` (a failure after a write landed), from the job command (a launch failure or veto), from `sync` (a canceled, vetoed or failed job; the repair step; an expired or rejected `launch` pending). Two conditions must hold. (a) The agent state is `never_ran`: Agent adoption returned `none` (the label query succeeded, wtctl was readable, and no candidate was accepted) or an adopted agent whose runs all ended in phase `launch`. An adoption result of `unknown` (a failed list or wtctl read, or several accepted candidates) means no restore in this run: the item keeps its phase, `sync_failed` or `agent_missing` shows why, and the next `sync` retries. An agent that ran: no restore; the job's end sets `job_failed`. (b) The ticket lease is held by the caller.

Order. 0. Cancel every non-terminal job of the item except the job whose id equals `JOBSCTL_JOB_ID` (a running restore never cancels its own job; that job ends by its own exit code): `jobsctl cancel <id>` by stored id, else `jobsctl show --unique-key ticket:<site>:<KEY>` and cancel only a job whose labels hold `owner=ticket-work`. `live` (exit 20) from the cancel of another job means a runner is active: stop the restore, retry at the next `sync`.

The restore then reads the live ticket once (`ticketctl get KEY --site <site> --fields status,assignee,sprints --json`) and acts on live values only; the stored step statuses are never consulted.

1. Status, when the start changed it (`started_status` is set). Live status equal to `previous.status`: nothing to do. Live status equal to `started_status`: `ticketctl transition KEY --site <site> --to <previous.status> --if-status <started_status> --dry-run`, then applied with `--yes --expect-plan <hash>`. Any other live status (a human moved the ticket): leave it, skip steps 2 and 3, set `restore_failed` (detail `status_moved`).
2. Assignment, when `intent.assign` is true. Live assignee is the account: `ticketctl update KEY --site <site> --assign none`. Live assignee empty: nothing to do. A different live assignee: leave it, set `restore_failed` (detail `assignee_changed`).
3. Sprint, when `intent.sprint_id` is not null. Live open and future sprint ids equal `previous.sprint_ids`: nothing to do. Equal to `[intent.sprint_id]`: if `previous.sprint_ids` is empty `sprint remove KEY --site <site>` (ticketctl warns `other_sprints_dropped`); if it has exactly one id `sprint add KEY --site <site> --sprint <id>`; more than one previous id cannot be restored: `restore_failed` (detail `sprints_unrestorable`); a closed previous sprint cannot be restored. Any other live set: leave it, `restore_failed` (detail `sprints_changed`).
4. Release the claim (`--failed` or plain per Claim release rules), set `cleanup.claim: released`, phase `failed`, `restore_state: done`, resolve any open `start` record of the item, and fire `post-start-failed` with the result. The agent id, if any, is kept; a restart resumes that parked agent.

A lower failure of a step (exit 11, 12, 13, 20, 21, 22 other than the cases above) sets `restore_failed` with `detail: {step, lower_code, reason}` (detail `step_failed`); later steps still run. `no_such_transition` or a closed sprint sets `restore_failed` with the details. The flow never guesses another route and skips `pre-` hooks; it is audited. `restore_on_failure: false`, or a board with no `started.to`, skips steps 1 to 3 and still runs step 4 (the claim is released and the item becomes `failed`). Rerunning the flow after a crash is safe because every step first compares the live value; `restore_state` (`none`, `done`, `failed`) prevents repeats. Actor: restore writes use `auto:ticket-work` (from `_job`), the sync's own actor (from `sync`) or the invoking actor (from `start`), and carry the human's identity of the start as a decision id `start-by:<actor>`. Basis: a restore applies ticket writes with `--yes` without a fresh human acceptance because it only undoes a start that a human accepted (or that `confirm: auto` or an enforced gate allowed), each step is guarded by the live value, and `restore_on_failure` (default true) is the config opt-in; this is a compensating action against design guide section 4.4, recorded in `design.md`.

## Teardown

A work item has one agent (the stored id); a restart after `failed` or `stopped` reuses it. After `pr_merged` (cleanup gating below), if the stored agent is not live: the merged pull request used is the landed merged pull request whose repository equals the work item's repository and whose `head_ref` equals the recorded branch; `agent-spawn teardown <agent_id> --merged-head <its merged_head_sha> --actor <actor> --decision-id ...` (the invoking actor, for example `auto:cron`). When no pull request matches, no teardown is attempted: `cleanup.teardown` stays `pending` and the attention `teardown_refused` is set with detail `no_matching_pr`. A torn-down agent (exit 10 with `details.status: torn_down`, from `teardown` or from the Agents step's `show`) counts as done whatever an earlier refusal was, including after a human ran `agent-spawn teardown` or `wtctl remove` by hand. Every refusal (`dirty`, `unpushed`, `in_use`, `repo_config_changed`, `held`, `live`, `locked`, `unlinked`, and `partial`) sets `teardown_refused` with the lower reason (for `held`, the holder agent ids from the lower error in the detail) and is retried at every `sync` (agent-spawn continues a partial teardown from its marker, so a retry is safe); a pre-teardown hook veto (exit 11) or escalation (exit 13) sets it with detail `vetoed` or `escalated`. `--force` is human-only and ticket-work never passes it. After teardown succeeds the claim is released plainly, `cleanup.teardown` is `done` and `cleanup.claim` `released`. `cleanup.teardown: false` in config skips teardown (`not_needed`) and releases the claim. A closed-unmerged work item is never torn down automatically.

Cleanup gating: cleanup (teardown, then claim release) for an item in phase `merged` runs once the outcome of the `pr_merged` event is final or an applied or declined outcome, and is not `pending` or a retry-on-change outcome (Events). While it waits, `cleanup.claim` stays `held`, the claim is renewed, and the attention `rule_failed` (or none, for pending) shows why. If the renewal is refused the claim is simply released (Claims). `stop KEY` on a `merged` item with outstanding cleanup is the human exit: it releases the claim, clears `teardown_refused` and `rule_failed`, and leaves `cleanup.teardown` as it is. Cleanup is never skipped because of the claim state.

## Slot contract

Skill slot `implement-ticket` (architecture §5.5): default skill `ticket-work:implement-ticket`, kind `implement`, default mode interactive.

- **Bundle.** The plugin `ticket-work` ships inside the package and is located with `importlib.resources.files('ticket_work') / 'plugin'`. It contains the skill, a reference file holding the skill marker, the four sandbox placeholder entries (`.claude/`, `.mcp.json`, `CLAUDE.md`, `CLAUDE.local.md`), and the bundled permission profile. The profile sets no permission mode and allows file edits inside the working directory only (`Edit(/${CWD}/**)`, `Write(/${CWD}/**)`, never a bare tool name), `git` and `gh` through Bash, and the read tools; other tools prompt the human (the interactive default). `agent.skill` and `agent.plugin_dirs` replace or add skills.
- **Kind and trust.** ticket-work always passes `--kind implement`, runs `agent-spawn launch --dry-run` first and verifies the kind check (Job command step 4); any warning is fatal (an unknown kind silently runs the third-party-reading review profile). The run is trusted (not third-party-reading): boards are semi-trusted (architecture §13.2 rule 7) and ticket text is still fenced. ticket-work never passes `--reads-third-party`.
- **Safety settings, per call.** `--permission-profile <bundled or agent.permission_profile>`, `--sandbox <agent.sandbox>` (default `off`: a sandboxed, `dontAsk` run cannot read `~/.config/gh`, `~/.ssh` or `~/.gitconfig`, has a domain-limited network and loses `GH_TOKEN`; a recorded deviation from design guide §11), `--setting-sources <agent.setting_sources>` (default `["project"]` for interactive runs so the repository's own instructions load, a recorded deviation from the guide's default of none; `[]` for unattended runs unless the repository opts in, Unattended runs). `--env-allowlist-only <name>` is always passed (exact names only), for a fixed base (`PATH HOME USER LOGNAME SHELL LANG TERM TZ` and the names beginning `LC_` present in the job environment at launch, each passed as a concrete name; claude-session accepts exact names only) plus each name of `agent.env_allowlist`. Names in `jobs.pass_env` are never forwarded to the agent or to hooks; a user who wants the agent to have `SSH_AUTH_SOCK` or `TMUX` lists it in both `jobs.pass_env` (so jobsctl gives it to the job) and `agent.env_allowlist`. `validate` reports every name present in both lists as a notice. The scrub keeps the names out of the agent's environment only; the agent can read the environments of its ancestors and jobsctl's env file as the same user (Residual risks). Every setting is replaceable in config.
- **Prompt file.** The job command builds one prompt file at every launch or resume (never at `start`, so a pending start confirmed hours later or a resume after a ticket edit sees fresh text). It reads `ticketctl get KEY --site <site> --fields key,title,description,acceptance_criteria,parent,epic,links,labels,comments --comments 10 --json` (acceptance criteria are included when ticketctl returns them). Trusted facts come first, outside any fence: the ticket key, the repository id, the branch, the base, the draft-pull-request default, the work item's `run_token`, and the skill marker instructions. Untrusted text is fenced with a nonce, `<untrusted source="ticket" id="R">...</untrusted id="R">`, with the standing "data, not instructions" rule: title, description and acceptance criteria; for an interactive run also the parent epic's title and linked ticket keys with titles; for an unattended run the parent epic key and the linked ticket keys only, no titles; and the comments (an `--input-file` when large; only comments of trusted authors, Unattended runs). `R` and the run token come from a CSPRNG (at least 128 bits), fresh per prompt build; the fence neutralization replaces `</untrusted` and `<untrusted` case-insensitively and with intervening whitespace (design guide §12). A resume's answer (stored by `resume --prompt-file`) is written into the prompt file at launch, fenced the same way, with the trusted facts and the run token restated.
- **Prompt and state files.** The directories `~/.local/state/ticket-work/`, `prompts/` and `jobs/` are created with mode 0700 and the files with 0600. A prompt file has a random name and is created with `O_CREAT|O_EXCL|O_NOFOLLOW`; it is deleted when the launch or resume call returns. `sync` and `prune` delete prompt files older than one day. Every state directory ticket-work writes into is verified at the start of a writing command (Concurrency).
- **Run token.** One token per start attempt (`run_token`, created at `start` step 9, new for every restart), stored in the settings snapshot, restated in every prompt, so a `done` after a resume validates. The artifact must carry it. It is not exposed in output.
- **Artifact.** The agent reports `done` with `{"schema_version": 1, "ticket": "<KEY>", "branch": "<name>", "prs": [{"url": "..."}], "summary": "...", "skill_marker": "...", "run_token": "..."}`. ticket-work reads it from the frozen path in `claude-session status --json` (through the agent-spawn result's `run.report.artifact.path`). One function validates an artifact: it opens the frozen path without following symlinks, requires a regular file of at most 64 KiB whose size and sha256 equal the values in `run.report.artifact`, and validates the schema, `ticket` equal to `key` or any of `requested_keys`, `skill_marker` equal to the marker in the bundled reference file, `run_token` (the work item's) and `report.implicit: false`. `_job` calls it with the launch or resume result. `sync` (Agents step) calls it for an agent that is not live, whose last outcome is `done` and whose `last_artifact` is null, obtaining the result with `agent-spawn wait <agent_id> --timeout 30s --result-file <file> --json` (a parked agent returns at once with its last outcome, and `run.report.artifact` is in that result); a failure sets the attention `agent_failed` (detail `artifact_invalid`, or `artifact_missing` when the result has no artifact) and the event `agent_failed`. A valid artifact stores `last_artifact` `{prs: [{url, pr_id, verdict}], branch, summary_sha256}` (`pr_id` null and `verdict` `unverified` until the Read step verifies each url). Later syncs read the stored copy only. A wrong skill name exits 0 `done` with no artifact, so a missing or mismatching artifact is a failed run (`agent_failed`). A `done` run with an empty `prs` that finds no linked pull request at the next `sync` sets the attention `agent_failed` with detail `no_pr`. The agent's `prs` and `branch` are claims: each pull request is verified through forgectl (PR linking, Discovery and read). `summary` is untrusted.
- **Other reports.** `blocked` and `needs-input` carry only a reason (`report.status` tells them apart); the agent is not asked for an artifact. The reason is stored in `last_report.summary` (untrusted, sanitized on output).
- **Self-labeling** (`agent-spawn label add --session`) is optional for the agent; a shell variable in a command is denied inside an isolated run, so ticket-work never depends on it.

### Unattended runs

A run is unattended when it is started by `start --auto` or its mode is `headless`. Three rules apply. (a) Comments reach the prompt only from authors that are trusted and only when the comment is unedited and was not written by automation: the comment is `own` (ticketctl's comment object) or its `author.account_id` is in `boards.<name>.trusted_authors`, its `updated` equals its `created`, and for an `own` comment `authored_by_ticketctl` is false and `actor_kind` is not `auto` (a comment posted through ticketctl by a tool or agent under the user's account is left out like another author's). Account comparison is exact on `account_id`, never on `display_name`; a null `account_id` matches nothing except `["*"]`. Interactive runs obey the same comment rule. The prompt notes that comments were omitted. (b) An unattended start requires that the ticket's `reporter` is the user's own account or is in `boards.<name>.trusted_authors` (`["*"]` means any reporter, an explicit choice of the user); otherwise the start exits 20 `untrusted_reporter` (and releases per Claim release rules). (b) is evaluated at `start`, at every `resume` that makes a run unattended, and by `_job` before the first launch of an unattended run. The reporter check is a heuristic about who created the ticket, not provenance of its text (ticketctl exposes no last editor), so anyone who can edit the ticket can change what the agent reads; see Residual risks. (c) The default `setting_sources` of an unattended run is `[]`; a repository opts in with `repos.<id>.agent.setting_sources: [project]`. An absent per-repository key is never an opt-in. The bundled permission profile also denies `Read` of `~/.ssh/**`, `~/.config/gh/**`, `~/.config/glab-cli/**`, `~/.aws/**`, `~/.gnupg/**`, `~/.netrc`, `~/.claude/**` and the configuration directories of the awkit tools; this is guidance for a trusted unsandboxed agent, not a boundary (Residual risks).

## Hooks

Hooks follow design guide §8: configured under `hooks.<name>` as `{cmd, timeout, async}` lists, run via `sh -c` in their own process group, JSON on stdin, default timeout 30 seconds. Pre-hook exit 0 continues, exit 13 escalates, any other non-zero vetoes (exit 11). The hook environment is the fixed base of the Slot contract plus `TICKET_WORK_HOOK`, `TICKET_WORK_ID` (the work id) and `TICKET_WORK_OBJECT_TYPE` (`work`); `jobs.pass_env` names are removed. A hook's returned `decision_id` is validated against the grammar `^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$` (no leading `-`); every value that originates outside ticket-work is passed to a lower tool in the `--opt=value` form. Per-invocation `--hook <name>=<cmd>` is accepted by `start`, `resume`, `confirm`, `stop`, `sync`, `link` and `unlink`.

| Hook | Runs | Notes |
|---|---|---|
| `pre-enqueue` | `start` step 7, on the plan, before the Confirm decision | veto releases the claim (Claim release rules); escalation records a pending start |
| `pre-transition` | on the plan of every ticketctl write ticket-work makes (transition, sprint, comment), before the Confirm decision (`start` step 7) | veto or escalation applies the hook outcomes of Apply outcomes; skipped by the restore flow (which is audited) |
| `pre-launch` | in the job, before `agent-spawn launch` or `resume` | veto restores the start when the agent never ran; escalation holds the job (exit 13) |
| `post-link` | a link or unlink | |
| `post-status` | an event was applied, recorded as pending, skipped, declined or failed, including `pr_merged_partial` | |
| `post-start-failed` | a start was restored | |
| `post-pending` | a pending confirmation was recorded | |
| `post-attention` | an attention reason was set | closed `reason` (Attention reasons) |

Payload (schemas in `schemas/hooks/`): the common fields `tool`, `hook`, `event_id` (post hooks), `object_type: work`, `object_id`, `repo` (the work item's repository id), `labels` (`ticket=<KEY>`, `owner=ticket-work`, `repo=<repo id>`, `board=<name>`), `board`, `site`, `key`, `phase` (null for a `pre-enqueue` hook when no work item exists), `actor` and `decision_ids`, plus by hook: `pre-enqueue` the common fields only; `pre-launch` adds `mode`, `skill`, `branch`, `base` for gates; `pre-transition` adds `event`, `rule` (the event name of the status-map rule that applies, `started`, `pr_merged`, ..., or null for a hook with no rule) and `plan` (`action`, `steps`, `current_status`, `target_status`, `plan_sha256`); `post-link` adds `change` (`link` or `unlink`) and `pr_ids`; `post-status` adds `event` (including `pr_merged_partial`), `rule`, `outcome` (`applied`, `pending`, `skipped`, `declined`, `failed`), `reason`, `pending_id` and `pr_ids`; `post-start-failed` adds `reason` (a ticket-work or lower reason string), `restore_state` and `dedupe_key` (`<work id>:start_failed:<seq>`); `post-pending` adds `pending_id`, `action`, `event`, `summary` (trusted text), `expires` and `dedupe_key` (the pending id); `post-attention` adds `reason` and `dedupe_key`. `plan.current_status` and `target_status` are host status names: allowed, untrusted, capped at 64 characters. Payloads carry keys, ids, `phase`, enums and counts, never ticket, pull request or model text. Post hooks are delivered at least once through an outbox, after the command prints its result, with `event_id`; a failed post hook is logged and never fatal, and is retried at later syncs at most 5 times, then marked dead in the outbox and logged.

## Exit codes

| Exit | Meaning |
|---|---|
| 0 | success (including `unchanged`, `already_running`) |
| 1 | internal error (reasons `lease_lost`, `lease_timeout`) |
| 2 | usage, invalid config, `human_only` |
| 10 | not found (work item, pending record, ticket) |
| 11 | a pre-hook vetoed |
| 12 | a lower tool failed or is missing (`lower_failed`, `tool_missing`, `tool_too_old`, `partial_results`, `repo_unresolved`, `schema_newer`) |
| 13 | needs a human: a pending confirmation was recorded, or a hook escalated, or the job was held |
| 14 to 18 | the job command only: the agent's outcome passed through |
| 20 | refused, with `reason` |
| 21 | ambiguous key |
| 22 | `start`: `nothing_to_start` (reasons `empty`, `no_capacity`, `pending_exists`, `scan_exhausted`) |

Refusal reasons (exit 20): `live`, `precondition_failed`, `unmapped`, `already_started`, `not_active`, `not_current_job`, `claimed`, `claim_lost`, `declined`, `expired`, `not_pending`, `stale_plan`, `not_linkable`, `untrusted_reporter`, `foreign_claim`, `job_key_taken`, `busy`, and the reasons of a lower tool passed through. Reasons of ticket-work's own at exit 12: `unsafe_state_dir` (code `lower_failed`). Exit 2 reasons: `human_only`, `invalid_combination`, `stdin_conflict`, `invalid_config`, `missing_option`. Exit 22 means "nothing to do" here, not invalid input (ticketctl's meaning).

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

With `--json`: exit 0 and 22 print the command's object; 13 prints the pending object (or the held result); 1, 2, 10, 11, 12, 20 and 21 print the error envelope `{"error": {"code", "message", "reason", "details", "tool", "lower_code", "lower_error", "hook", "hook_stderr", "decision_ids"}}`. `tool` names the lower tool that failed (`ticketctl`, `ticket-queue`, `forgectl`, `agent-spawn`, `jobsctl`, `wtctl`); `lower_error` is its whole `error` object verbatim and untrusted; `lower_code` is the lower tool's own `code` (an untrusted string); `decision_ids` is an array (empty when none). Errors go to stderr as well.

Error codes by exit: 1 `internal` (reasons `lease_lost`, `lease_timeout`), 2 `invalid_argument`, 10 `not_found`, 11 `hook_vetoed`, 12 `lower_failed` / `tool_missing` / `tool_too_old` / `partial_results` / `repo_unresolved` / `schema_newer`, 20 `refused`, 21 `ambiguous_key`.

The `reason` field is a snake_case string `^[a-z][a-z0-9_]{0,63}$`: ticket-work's own reasons are the lists of Exit codes, and a lower tool's reason is passed through unchanged. `details` shapes per reason: `precondition_failed` `{rules[], current_status, unknown[]}`, `not_linkable` `{why}`, `live` `{agent_id, job_id}`, `already_started` `{phase}`, `unmapped` `{why}`, `untrusted_reporter` `{reporter}`, `not_current_job`, `not_active` `{phase, cleanup?, hold_reason?}`, `claim_lost` `{lower_reason}`, `stale_plan` `{new_pending}`, `foreign_claim` `{key}`, `job_key_taken` `{job_id}`, `busy` `{}`.

## Output sanitizing

Every human-readable print of an untrusted field (`title`, `last_report.summary`, `attention` detail, `lower_error`, `hook_stderr`, host status names, the dialog) goes through one sanitizer: C0, C1, DEL, bidi and other invisible format characters become visible markers and the text is cut to a line limit. `--json` is not sanitized (consumers sanitize).

## Objects

The schema files under `schemas/` are the field lists; this section names each shape and the decisions behind it. Every schema is closed (`additionalProperties: false`): producers are strict, consumers must ignore unknown keys.

- **`work`** is the work item object in `start`, `resume`, `stop` and `show` (`list` prints work summaries), and the work id string in `confirm`, `reject`, `link`, `unlink`.
- **Nothing-to-start object** (exit 22 of `start`): `{nothing_to_start: true, reason: empty|no_capacity|pending_exists|scan_exhausted, refused?}` (`refused`: `[{key, reason}]`, present for `scan_exhausted`). `schemas/cli/start.json` is `oneOf` the start result and this object.
- **Start result** (`schemas/cli/start.json`): `work`, `claim` (ticket-queue's claim object verbatim), `plans` (`{transition: plan|null, sprint: plan|null}`), `applied` (a list of `{step, status, attempt_id?}` where `step` is ticketctl's step kind: `assign`, `transition`, `sprint_add`, `sprint_remove`, `set_fields`, `add_comment`; and `status` is `planned|applied|unchanged|skipped|failed|unknown`), `pending`, `job` (`{id, status?, foreground?, exit_code?}` or null; `id` is null for a foreground run, whose exit code is the job's), `warnings` (`{code, message}` with the closed codes `sprint_failed`, `assign_skipped`, `existing_job`, `queue_full`, `pass_env_undefined`, `label_skipped`, `lookup_incomplete`, `incomplete_discovery`), `dry_run`. `work` is not null for a pending start (it has a stored item in phase `pending`); it is null only for a dry run.
- **Plan** (hooks and pending): `{action: transition|sprint_add|sprint_remove|update|comment, steps, current_status, target_status, plan_sha256, changes?}`; the pending record holds `plan_sha256` as a map step to hash and `details.changes`. Status names are host text: untrusted, sanitized, at most 64 characters.
- **Work item** (`schemas/cli/show.json`): `id`, `site`, `key`, `requested_keys`, `board`, `title` (untrusted), `phase`, `needs_attention` (boolean), `attention` (array of `{reason, detail, since}`), `repo`, `branch`, `base`, `holder`, `claim` (`expires_at`, `renewed_at`, `state`), `previous` (`status`, `sprint_ids` (non-negative integers)), `started_status`, `steps` (`[{step: transition|assign|sprint_add, status}]`, the display of the start's attempted writes; restore never reads it), `job` (`{id (string or null), status, foreground (boolean)}`), `agent` (`id`, `status`, `needs_attention`; the last is agent-spawn's own value as a string), `links`, `pending` (ids), `cleanup` (always present: `teardown` `not_needed|pending|done|refused`, `claim` `held|released`), `restore_state`, `last_report` (`status`, `summary` untrusted), `last_artifact` (`{prs: [{url, pr_id, verdict}], branch, summary_sha256}` or null; `verdict` is `linked`, `rejected` or `unverified`), `rejected_claims` (`[{url, why}]`), `merge_wait` (`agent_unfinished`, `others_open`, `not_landed`, or null), `labels` (`ticket=<KEY>`, `owner=ticket-work`, `repo=<repo id>`, `board=<name>`; the filter set of `list --label`), `created`, `updated`. The settings snapshot, the run token and the internal fields (`intent`, `start_assignee`, `last_written_status`, `run_started_at`, `pending_answer`, the foreground marker) are stored and not printed. `show` adds `pending_records` (full records) and `events` (at most 20, `{event, event_key, outcome, reason, ts, rule, pending_id}`).
- **Work summary** (`schemas/cli/list.json`): the work item without `requested_keys`, `base`, `holder`, `claim`, `previous`, `started_status`, `links`, `cleanup`, `restore_state`, `last_report`, `steps`, `last_artifact`; `attention` is an array of reason names; adds `prs` (`[{pr, pr_state, draft, link_state, counts}]`: `pr_state` is `open`, `closed`, `merged` or null before the first read, `draft` a boolean or null, `link_state` the link state) and keeps `labels` and `merge_wait`; `job` may be null or have a null `id` (a foreground item); the list output is `{"items": [...], "count": N}`.
- **Link**: `pr_id`, `repo_id`, `pr`, `repo`, `tier` (`claimed`, `branch`, `title`, `manual`), `state` (`linked`, `candidate`, `ignored`, `missing`), `counts`, `label_synced`, `facts` (`state` `open|closed|merged`, `draft`, `head_sha`, `head_ref`, `base_ref`, `is_fork`, `merged_head_sha`, `updated_at`, `activity_at`), `linked_at`.
- **Sync report** (`schemas/cli/sync.json`): `items` (per work item: `id`, `phase`, `events` (`{event, event_key, outcome, reason}`), `applied`, `pending`, `errors`, `lease_held`), `claims_released` (integer), `already_running`, `rerun`, `partial`, `dry_run`, `errors` (`{work_id|null, step, code, message, tool|null, lower_error|null}`); an item entry also has `would_events` (event names) in a dry run; `step` is one of `lease`, `expiry`, `repair`, `claims`, `agents`, `jobs`, `discovery`, `read`, `stale`, `rules`, `cleanup`, `hooks`.
- **resume**: `{work, mode, job|null, pending|null, warnings, dry_run}`. **stop**: `{work|null, stopped, applied[], pending|null, claim_released, dry_run}` (`pending` is a `transition` record). **link**: `{work, link, changed, promoted, applied[], dry_run}`; **unlink**: `{work, pr_id|null, changed, ignored, dry_run}`. **pending**: `{items, count}`; **confirm**: `{pending, work, applied, job|null, new_pending|null, warnings}`; **reject**: `{pending, work, claim_released}`. **cron install**: `{installed, changed, sync_interval, start_interval|null, block[], dry_run}`; **cron uninstall**: `{installed: false, changed, dry_run}`. **export**: audit records (no log export). **prune**: `{dry_run, removed: {work_items, links, pending_resolved, pending_expired}, skipped, warnings}` (the `--item` flag is input only). **validate**: exit 0 `{ok, probe, tools[], boards[], problems[], warnings[]}`; `problem` and `warning` are `{code, message, board|null, tool|null}`.
- **`_job`**: internal, its output is not a contract; exit 13 of `_job` has no object.
- **Pending record**: Pending confirmations. `escalated_by` is a hook name or `ticketctl`. `details` holds `changes`, `plans`, `overrides`, `unattended`, `previous`, `intent` (a `start` record), `superseded_by`, `superseded_by_event`, `rejected_by`, `reason`, `hint`, `apply_error` and, for a `launch` record, `job_id` and `attempt`.
- **Launch summary hash**: sha256 over the sorted JSON of `{repo, base, branch, mode, sandbox, setting_sources, skill, reporter_account_id, unattended}`.
- **Hook payloads**: Hooks.

## Configuration

`~/.config/ticket-work/config.yaml` plus `config.d/*.yaml` (design guide §5), validated at load (`schemas/config.json`, `config.example.yaml`). Precedence: flags, `repos.<id>`, environment, global config, defaults. Top-level and board objects are closed: a key the implementation adds needs an interface change first.

| Key | Default | Meaning |
|---|---|---|
| `me.name` | OS user | actor name |
| `instance` | the hostname lower-cased, characters outside `[A-Za-z0-9._-]` replaced by `-`, cut to 64, `host` when empty | part of the claim holder `ticket-work:<instance>`; the store records the instance at first run and refuses a different value (exit 2 `invalid_config`) |
| `boards.<name>.site` | none (required) | the ticketctl site (one board per site) |
| `boards.<name>.queue_board` | none | the ticket-queue board this board takes tickets from |
| `boards.<name>.sprint_board` | none | the board passed to `sprint add --board`; needed when a site has several boards |
| `boards.<name>.trusted_authors` | `[]` | account ids or `["*"]`; empty means only the user's own account (Unattended runs) |
| `boards.<name>.repos` | none (required) | ordered repository rules |
| `boards.<name>.branch.types` | `{default: feat}` | branch type by issue type (`^[a-z][a-z0-9-]{0,19}$`) |
| `boards.<name>.preconditions` | `[]` | named checks |
| `boards.<name>.status_map` | `{}` (`started` required to start) | event rules; keys are the 8 events |
| `boards.<name>.link_comment` | `false` | comment on `pr_opened` |
| `defaults.confirm` | `ask` | default for a rule's `confirm` |
| `start.max_pending` | `1` | unresolved pending starts allowed under `--auto` (the gate compares the open count with it) |
| `start.scan_limit` | `5` (1 to 20) | claims one run of `start --auto` may take while refusing candidates |
| `pending.start_expiry` | `24h` | pending start lifetime (at least `1m`) |
| `pending.expiry` | `7d` | other pending lifetime (at least `1m`) |
| `claim.ttl` | ticket-queue's default | passed with `--ttl` when set (a duration or null; at most `claim.max_ttl`, checked by ticket-queue) |
| `claim.renew_below` | `0.5` | renew when this fraction of the TTL remains (in (0, 1]) |
| `claim.orphan_after` | `15m` (at least `5m`) | release or repair grace: a claim of this store with no work item, or an item stuck in `applying`, is handled after this age; config file only |
| `sync.overlap` | `1h` | discovery watermark overlap |
| `sync.reread_open_after` | `1h` | re-read open pull requests at least this often |
| `sync.pr_idle_after` | `14d` | `pr_idle` threshold |
| `sync.call_timeout` | `120s` (`5s` to `30m`) | the timeout of every lower call; on expiry the exact child process is stopped and the call fails transient |
| `agent.skill` | `ticket-work:implement-ticket` | the slot skill |
| `agent.mode` | `interactive` | `interactive` or `headless` |
| `agent.sandbox` | `off` | `off`, `preferred` or `required` |
| `agent.permission_profile` | bundled file | replaces the bundled profile |
| `agent.setting_sources` | `["project"]` interactive, `[]` unattended | Claude setting sources (`user`, `project`, `local`); an unattended run uses `[]` unless `repos.<id>.agent.setting_sources` opts in; unset in `repos.<id>.agent` means no opt-in |
| `agent.env_allowlist` | `[]` | names added to the fixed base of `--env-allowlist-only` |
| `agent.plugin_dirs` | `[]` | extra plugin directories |
| `agent.model` | none | passed with `--model` when set |
| `agent.timeout` | none | passed as `--timeout` when set |
| `jobs.enabled` | `true` | use jobsctl (required for `start --auto`) |
| `jobs.queue` | `tickets` | jobsctl queue (`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`); config file only |
| `jobs.pass_env` | `[]` | `--pass-env` names for the job's own tool calls (credentials come from jobsctl's env file); never forwarded to the agent or hooks; `validate` reports a notice when `agent.mode` is `interactive` and the list lacks `TMUX` (an interactive launch from a job may need `TMUX` and `SSH_AUTH_SOCK`; still to verify) |
| `jobs.kill_grace` | `120s` | `--kill-grace` |
| `cleanup.teardown` | `true` | tear down after `pr_merged` |
| `restore_on_failure` | `true` | run the restore flow |
| `retention.work` | `90d` | `prune` age |
| `retention.pending` | `30d` | `prune` age for resolved pending records |
| `hooks.<name>` | `[]` | hook lists; entries `{cmd, timeout (seconds or duration, 1 to 600), async}` |
| `tools.<name>` | the tool's name | executable path per sibling |
| `repos.<id>` | none | per-repository overrides of `agent.*` (all keys), `cleanup.teardown` and `restore_on_failure` only |

The store id is created at first run from a CSPRNG (128 bits, 26 characters of `[a-z2-7]`), kept in `meta`, and used as the claim label `store=<store id>`; a copied state directory is a clone and needs a new `instance`.

Name grammars: variable names `^[A-Za-z_][A-Za-z0-9_]{0,127}$`, hook decision ids as in Hooks. `repos.<id>` wins over the environment, the global config and the defaults; flags win over `repos.<id>`.

## Environment variables

Only these scalars can be set as `TICKET_WORK_<KEY>` (nested keys joined with `__`): `me.name`, `instance`, `jobs.kill_grace`, `sync.overlap`, `sync.reread_open_after`, `sync.pr_idle_after`, `claim.ttl`, `claim.renew_below`, `pending.start_expiry`, `pending.expiry`, `retention.work`, `retention.pending`. Safety, path and autonomy settings (`agent.*`, `jobs.queue`, `claim.orphan_after`, `start.*`, `sync.call_timeout`, `tools.*`, `defaults.confirm`, `cleanup.*`, `restore_on_failure`, `boards.*`, `hooks.*`) are config-file only. Structured config (boards, hooks, rules) cannot be set from the environment. ticket-work reads no credentials: each sibling tool reads its own, and the job receives the names in `jobs.pass_env` from jobsctl's env file. `XDG_CONFIG_HOME` and `XDG_STATE_HOME` redirect config and state.

## Labels

ticket-work labels the agent and the job: `ticket=<KEY>`, `owner=ticket-work`, `repo=<repo id>` (agent-spawn adds `job=<job id>`). It adds `pr=<host/path#N>` to the stored agent when a link is made (for review-respond's lookup; never evidence for a link). Claims made by ticket-work carry the label `store=<store id>`. The work item's own `labels` (`ticket`, `owner`, `repo`, `board`) are the filter set of `list --label`. Labels are not authenticated against trusted agents, so ticket-work verifies every link against forgectl and every agent against its own records before an external action; labels only find candidates.

## Files

`~/.local/state/ticket-work/`: `state.db` (private), `audit.jsonl` and `log.jsonl` (public append-only contracts, `schemas/audit.json` and `schemas/log.json`), `prompts/` (prompt files with random names, mode 0600, deleted when the launch or resume call returns), `jobs/` (the job's cwd, mode 0700). Schema migrations are additive.

## Audit and log

Every external action appends an `attempted` record before the write and an outcome record after it (pairs share `attempt_id`): `transition`, `sprint_add`, `comment`, `restore`, `link`, `unlink`, `launch`, `resume`, `teardown`, and the pending confirmations (`pending_confirm`, `pending_reject`, `pending_expire`). Fields: `v`, `seq`, `ts`, `actor`, `decision_id` (array), `attempt_id`, `target` (work id), `action`, `inputs`, `result` (`attempted|ok|failed|partial|unknown`), `changed`, `reason` (an error reason, snake_case, or null). `inputs`: `work_id`, `event`, `rule`, `plan_sha256`, `pr_id`, `pending_id`, `lower_attempt_id` (the lower tool's `attempt_id`, for correlation); all optional. A `start` or `stop` has no audit action of its own: its claim writes are in ticket-queue's audit and its ticket writes in ticketctl's. `log.jsonl` records are defined by `schemas/log.json`, which is normative for them. The attribution of an agent's own commits and pull requests is the implement skill's job (commit trailers and the pull request body).

## Concurrency

Every command that writes the store or contacts a lower tool for a write takes leases (design guide section 4.3). The sync lease is one row, taken by `sync` for its whole run. The ticket lease is one row per work id (`site:KEY`); `start`, `resume`, `stop`, `link`, `unlink`, `confirm`, `reject` and the per-item steps of `sync` take it, `start KEY` before the claim and a keyless `start` right after it; `_job` takes it only for its short sections (loading the item, storing the agent id and the result, the restore flow) and waits for it up to 60 seconds. A command that cannot take a ticket lease within 30 seconds exits 20 `busy`; `sync` skips the item (`lease_held: true`, no error). A lease records the holder PID, the holder's process start time, the boot id and an expiry (fixed: heartbeat every 10 seconds, expiry 60 seconds ahead); the heartbeat stops when a lower call outlives `sync.call_timeout`. A lease whose holder is dead (the PID is gone, its start time or the boot id differs) may be taken over; a lease whose holder is alive is never taken over, even when it expired (a suspended machine keeps its PIDs). Every store write checks in the same transaction that the writer still holds its lease; a lost lease aborts the command with exit 1 (`lease_lost`). No lease is held across `agent-spawn launch`, `resume` or `wait`, across a job queue wait, or while a run of the agent is going on (a foreground `start` releases its lease before the job command runs); `start` holds the ticket lease during its confirmation dialog and `sync` holds the sync lease during its dialog, each dialog timing out after 10 minutes. A second `sync` exits 0 with `already_running: true` and sets the store flag `sync_rerun`; the running `sync` reads and clears the flag in the same transaction that releases the sync lease and runs its steps once more when the flag was set. Every state directory ticket-work writes into is verified at the start of a writing command (owner is the user, mode 0700, no symlink component) and the command exits 12 (`unsafe_state_dir`) otherwise. Whether an agent is live is asked of agent-spawn, never inferred from a lease.

## Dependencies

| Tool | Binding | Used for |
|---|---|---|
| ticketctl | A | ticket reads (`get --fields`, comments), transitions, sprints, comments, restore; `sites resolve` (offline) for key resolution |
| ticket-queue | A | `next --claim`, `claim --label`, `claims` (with `refresh` scheduled in cron), `release` |
| forgectl | A | pull request discovery and state: `prs`, `show`, `whoami`, `snapshot` (minimum 0.52.0) |
| agent-spawn | A | `launch --dry-run`, launch, resume, wait, list, show, label, teardown |
| jobsctl | A (required for `start --auto`; optional otherwise) | the `tickets` queue, capacity, `show`, `cancel`, `retry`, `resolve` |
| wtctl | A | `wtctl locate` before a start; `wtctl show` for agent adoption |

A missing required tool is exit 12 `tool_missing` naming its install command. The minimum versions of the siblings that implement their designed interfaces are pinned when implementation starts.

## Upgrades

The `schema_version` of `state.db` is additive-only. A newer database than the tool exits 12 (`schema_newer`). Hook payloads and `--json` outputs: producers are strict (closed schemas), consumers must ignore unknown keys.

## Residual risks

- Two machines with separate stores can both pass the start checks in the same second; Jira's live status check and `--if-status` make the second transition `unchanged`. There is no cross-machine lock. Two state directories on one host need different `instance` values; `start KEY` compares the `store` label of an existing claim with this store's id and refuses a foreign claim (`foreign_claim`), but a copied state directory shares the id (a clone).
- Labels and an agent's artifact are claims; verification relies on forgectl and ticket-work's own records. `skill_marker` and `run_token` are anti-accident checks, not defenses against forgery.
- A trusted, unsandboxed implement agent can run any command the user can; the bundled profile only guides it, and the unattended rules (Unattended runs) reduce but do not remove the exposure.
- ticketctl's confirmation prompt is not a boundary against a caller that can allocate a pty (architecture §13.1); the same holds for `confirm --yes`.
- `plan_sha256` has no expiry; ticket-work's pending expiry bounds the window.
- A worktree root trusted once in the Claude UI removes the trust dialog for every later worktree (agent-spawn's advice), so project settings of a base branch run unattended only where a repository opted in.
- A human `agent-spawn resume` of a held job's agent leaves the agent outside any job: its slot is not counted and `jobsctl cancel --force` does not reach it.
- `jobs.pass_env` and the environment allowlist prevent accidental ambient exposure only: a trusted unsandboxed agent can read `/proc/<ancestor>/environ` of the job, the supervisor and `claude-session exec`, and jobsctl's mode-0600 env file; only `sandbox: required` is a boundary.
- The reporter rule is not provenance: a user who may edit the ticket can change the description the agent reads after the check; `_job` repeats only the reporter test.
- The claim states of ticket-queue are as fresh as its last `refresh`; `done`, `gone` and `reassigned` can be noticed up to a renewal interval late unless a cron `ticket-queue refresh` runs.
- The early trigger "pr-watch: PR merged or closed, then ticket-work sync" has no producer in 0.x; `sync` from cron is the guaranteed path.
- forgectl's `hidden_repos` setting silently drops pull requests from every listing (no `complete: false`); a mapped repository that is hidden is never discovered, while the `claimed` tier and `link` still work because they use `show`.

## Platform notes

Linux, WSL and macOS. tmux is needed only for interactive agents (through agent-spawn); `--mode headless` needs none.
