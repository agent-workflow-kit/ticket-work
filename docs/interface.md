# ticket-work: interface

Status: 0.1.0-design (2026-11-13). This document is the single normative source for ticket-work's rules. `design.md`, the README and the architecture link to its headings and never restate its tables. Section references (architecture §N, design guide §N) point to `../awkit-docs/architecture.md` and `../awkit-docs/design-guide.md`.

ticket-work owns the lifecycle of a worked ticket: it claims a ticket, applies the board's start changes (assignment, sprint, status) after a confirmation, launches an implement agent in its own worktree, links the agent's pull requests to the ticket, applies a per-board status map as those pull requests move, and tears the work down after the merge. It is a workflow tool (layer 3) and a skill wrapper for the `implement-ticket` slot (design guide §11). It works standalone from a terminal and from cron; it never depends on the harness.

## Overview

- **Work item.** One record per worked ticket, keyed `site:KEY`. It is ticket-work's own store (`state.db`); everything another tool owns (the claim, the ticket, the pull request, the job, the agent) is re-read from that tool on each `sync`. The store holds only what no other tool owns: the previous status, assignee and sprint ids for a restore, the pending confirmations, the claim holder, the job id, the agent id, the linked pull requests with their last-seen facts, the applied events and the attention flag.
- **Board.** A named config entry with a ticketctl `site`, the rules that map a ticket to a repository, the branch naming, the preconditions and the status map. ticket-queue has its own boards; ticket-work boards are matched to them by `site` and the ticket's facts, never by name.
- **Link.** The relation between a work item and a pull request, recorded with the evidence that justified it (`tier`).
- **Pending confirmation.** A recorded action that needs a human (design guide §4.4).
- **Holder.** The opaque claim holder `ticket-work:<instance>` (see Configuration, `instance`).

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

`KEY` is a ticket key or `site:KEY`; a bare key that matches work items on several sites exits 21 (`ambiguous_key`, `details.candidates`). `PR` is a URL or `host/<full project path>#N`. Ticket keys follow ticketctl's grammar and are printed upper-case.

### Global flags

`--json`, `--config PATH`, `--verbose`, `--quiet` (with `--verbose`: exit 2 `invalid_combination`), `--dry-run` (every command that changes state or contacts another tool for a write), `--yes`, `--actor ACTOR`, `--decision-id ID` (repeatable), `--version`.

- `--actor` follows ticketctl's grammar `^(human|auto):[A-Za-z0-9._@-]{1,64}$`. The default is `human:<me.name>` when stdin and stderr are TTYs and `/dev/tty` opens, otherwise `auto:unknown`. `cron install` writes entries that pass `--actor auto:cron`.
- `--yes` skips ticket-work's own confirmation dialog. It is accepted only with a human actor; with an `auto:` actor it exits 2 (`human_only`). It never bypasses a pending confirmation, a precondition, a gate or a refusal. Automation never passes it (design guide §4.4).
- Untrusted text never travels only in argv: `resume --prompt-file` takes a file or `-`. At most one `-` source per command (exit 2 `stdin_conflict`).
- `--config PATH` loads only that file (no drop-ins).

### start

`start KEY` claims that ticket; `start` with no key takes the top eligible ticket. `--board B` limits the choice to tickets of that board (ticket-queue board). `--skill`, `--mode` and `--sandbox` override the `agent.*` config keys for this start and are stored on the work item.

`start --auto` is the cron form: it is the only form that may run without a human. It applies the capacity gate of Start order step 1, records at most one pending start (unless the rule's `confirm` is `auto`), and never prompts.

The order of every start is fixed (Start order). A start that cannot proceed releases its claim (Claim release rules) and exits with the refusal. Output: the start result object (Objects).

Exit codes: 0 started (job enqueued, or the pending start was confirmed in the same call); 11 a `pre-enqueue` hook vetoed; 12 a lower tool failed; 13 a pending start was recorded or a hook escalated; 20 refused (`precondition_failed`, `unmapped`, `already_started`, `claimed`, `not_in_pool` ...); 21 ambiguous key; 22 `nothing_to_start`.

### resume

`resume KEY` continues the agent of a work item that is not finished. It requires phase `starting`, `working` or `in_review`, a held claim, and a parked agent (a live agent exits 20 `live`). It enqueues a job whose command resumes the same agent. `--mode` defaults to the mode of the agent's last non-promotion run; a human answering a blocked headless agent passes `--mode interactive`. `--prompt-file` carries the human's answer (fenced by ticket-work like every untrusted text, see Slot contract); `-` reads stdin.

If a job for this work item is held (hold reason `exit_13`), `resume` continues it with `jobsctl retry <id> --attempt N` (same job id); otherwise it adds a new job with the same unique key (a terminal holder of the key does not block). Without jobsctl it runs the job command in the foreground.

Exit codes: 0 enqueued; 10 no such work item; 11 a `pre-launch` veto (raised later, in the job; see Job command); 13 a pending launch recorded; 20 refused (`live`, `not_active`, `claim_lost`); 21 ambiguous key; 12 a lower tool failed.

### sync

`sync` is the only command that reads other tools besides `start`, `resume`, `link`, `confirm` and `_job`. It is idempotent, safe under cron and takes a lease (Concurrency). The order is fixed (Sync order). `sync KEY` restricts every step to that work item and to the repositories its board maps.

Output: the sync report object. Exit codes: 0 (including "already running", `already_running: true`); 12 a lower tool failed for part of the run (`partial_results`, `details.errors` per work item; the other items were still processed); 1 internal.

### list and show

`list` and `show` read only the store; they contact no other tool and run no hook. `list --json` prints `{"items": [<work item summary>...], "count": N}` ordered by `updated` descending. Without `--all`, items in phase `merged`, `stopped` or `failed` older than 24 hours are omitted. `--phase` is repeatable (OR); `--label` and `--pr` are ANDed. `show KEY` prints the work item with its links, pending confirmations, last report summary (untrusted) and the last 20 events; exit 10 when the key has no work item.

### stop

`stop KEY` ends ticket-work's activity on a ticket. It refuses (exit 20, `reason: live`) while the agent is live (nothing overrides `live`; stop the agent with `agent-spawn stop` first). Otherwise it applies the `stopped` rule of the board's status map if there is one (with that rule's `confirm`), releases the claim with a plain `release`, sets phase `stopped` and clears the attention flag. After that `sync` records the pull request facts for display but makes no transition, comment or teardown for the item. The agent and the worktree stay parked; removing them is `agent-spawn teardown`, a separate step (`--force` there is human-only).

`start KEY` on a `stopped` item claims the ticket again and reuses the existing agent and worktree by resuming it through the job command (the usual confirmation and preconditions apply, against the ticket's live status).

Exit codes: 0; 10; 13 (the `stopped` rule needs a confirmation: a pending confirmation is recorded and the item is stopped only when it is confirmed); 20 `live`.

### link and unlink

`link KEY PR` records a manual link (tier `manual`) after checking through forgectl `show` that the pull request is authored by the user's own account, lies in a repository the board maps, and is not already linked to another work item. Refusals (exit 20, reason `not_linkable`, `details.why`): `author_not_me`, `repo_not_mapped`, `linked_elsewhere`, `not_found`. A candidate (tier `title`) is promoted by `link`. `link` adds the `pr=` label to the agent (`agent-spawn label add <agent_id> pr=<pr>`; a replaced value needs `label remove` first), runs the `link_comment` rule if configured, fires `post-link`, and writes an audit record.

`unlink KEY PR` removes the link, removes the `pr=` label, and marks the pull request `ignored` for this work item so discovery never links it again. Both are idempotent.

### pending, confirm and reject

Design guide §4.4 applies. `pending` lists unresolved pending confirmations (`--all` includes resolved and expired ones until pruned). `confirm ID` and `reject ID` require a human actor (a TTY, or `--actor human:<user>`); otherwise exit 2 (`human_only`). The behavior of each pending action is in Pending confirmations.

### cron

`cron install|uninstall` writes or removes a managed crontab block (design guide §4.3): first line `# ticket-work managed`, last line `# ticket-work managed end`, an explicit `PATH`, the `XDG_CONFIG_HOME` and `XDG_STATE_HOME` lines when set, and the optional user-owned env-file prefix. It installs `ticket-work sync --quiet --actor auto:cron` every `--sync-interval` (default `10m`). With `--with-start` it also installs `ticket-work start --auto --quiet --actor auto:cron` every `--start-interval` (default `30m`); starting automatically is opt-in. An end-less block is never replaced.

### export, prune and validate

`export` prints audit records as JSON lines (`--since`, `--after-seq`, `--to PATH`, as ticketctl). `prune` deletes finished work items (phase `merged`, `stopped` or `failed`) older than `retention.work` (default 90 days) with their links and resolved pending records, and expired pending records older than `retention.pending`; it never touches `audit.jsonl`. `validate` checks the config and the sibling tools: each required tool is installed and at its minimum version, `ticketctl whoami` works per configured site, ticket-queue's `validate` passes, and every board has a `started.to`, a `started.from`, repository rules and a resolvable repository (`wtctl locate`); `--probe` also runs `forgectl whoami`. Exit codes 0 or 12 (problems listed in `details.problems`).

## Work item and phases

A work item's `phase` is derived at each `sync` from the other tools' facts; the store caches it for `list` and `show`.

| Phase | Meaning |
|---|---|
| `pending` | a pending start exists and nothing was applied to the ticket |
| `starting` | the start changes were applied (or there were none), the job exists, and the agent has not started a run |
| `working` | an agent exists and no linked pull request is open |
| `in_review` | at least one linked pull request is open (draft or ready) |
| `merged` | the `pr_merged` event fired (Status map); cleanup progress is `cleanup` |
| `stopped` | `stop` ran |
| `failed` | the launch never happened (a launch failure, a vetoed or canceled job) and the start was restored |

`needs_attention` is a separate flag with one closed reason (Attention reasons). A work item with an attention flag keeps its phase.

`cleanup` has `teardown` (`not_needed`, `pending`, `done`, `refused`) and `claim` (`held`, `released`).

### Attention reasons

`restore_failed`, `pr_idle`, `superseded`, `ticket_diverged`, `candidate_link`, `teardown_refused`, `agent_blocked`, `agent_failed`, `job_held`, `pending_expired`, `sync_failed`, `sprint_failed`, `claim_lost`, `agent_missing`. Every transition into a reason fires `post-attention` once (Hooks).

## Start order

1. **Gate (`--auto` only).** `capacity = jobsctl capacity --queue <jobs.queue>` `effective_free` (without jobsctl: `jobs.max_running` minus running job leases) minus the number of unresolved pending starts. A capacity of zero or less exits 22 (`nothing_to_start`, reason `no_capacity`). An unresolved pending start with `confirm` not `auto` exits 22 (reason `pending_exists`).
2. **Claim.** `start KEY`: `ticket-queue claim KEY --holder <holder>`; `start`: `ticket-queue next --claim --holder <holder> [--board B]`. A ticket-queue refusal (exit 20) is passed through (`details.lower_error`); exit 22 from `next` is `nothing_to_start` (reason `empty`). A claim is local: it writes nothing to the ticket system.
3. **Read.** `ticketctl get KEY --fields ...` for the facts the preconditions and the plan read, live. A key that moved is followed (the work item uses the canonical key and keeps the requested key).
4. **Resolve.** The board is matched by the ticket's site; the repository and base by the ordered rules (Ticket to repository and branch); a ticket that matches nothing is refused (exit 20 `unmapped`). The repository is checked with `wtctl locate --repo <id>`; a repository wtctl cannot resolve exits 12 (`repo_unresolved`) before anything is changed. An existing work item is handled by phase: `stopped` re-adopts; `failed` restarts (a new job under the same work item); any other phase is refused (exit 20 `already_started`; use `resume`).
5. **Preconditions.** Every rule of the board's `preconditions` is evaluated against the live ticket (Preconditions). A failure exits 20 (`precondition_failed`, `details.rules`).
6. **`pre-enqueue` hooks.** A veto exits 11, an escalation records a pending start (exit 13).
7. **Plan.** `ticketctl transition KEY --to <started.to> --assign <assign> --if-status <live status> --dry-run` (with `--resolution` only for a done target), then `ticketctl sprint add KEY --sprint <started.sprint> --dry-run` when the rule names a sprint. The live status must be one of the rule's `from` statuses, else exit 20 (`precondition_failed`, `details.rules: ["started.from"]`, `details.current_status`). The previous status, assignee and the open and future sprint ids are recorded from the dry-run `changes` before anything is applied.
8. **Confirm.** From a TTY, ticket-work shows both plans (the changes, never ticket text beyond the key) and asks once, reading the answer from `/dev/tty`; a decline exits 20 (`declined`, nothing stored, claim released). Without a TTY and without `confirm: auto` (or an enforced gate), ticket-work records a pending start (action `start`), fires `post-pending` and exits 13; the claim stays held (Pending confirmations).
9. **Apply.** For each write, the `pre-transition` hooks run first; then `ticketctl ... --yes --expect-plan <hash> --actor <actor> [--decision-id ...]`. A `stale_ticket` exit 20 re-plans once (step 7) and, for a human at a TTY, asks again; otherwise it fails the start with the restore flow. If the assign-and-transition call lands and `sprint add` fails, the start continues and sets `sprint_failed`. Any other failure after a step landed runs the restore flow and releases the claim with `--failed`.
10. **Record and enqueue.** The work item moves to `starting` and the event `started` is recorded. The prompt files are built (Slot contract) under the state directory. The job is added: `jobsctl add --queue <jobs.queue> --unique-key ticket:<site>:<KEY> --max-retries 0 --cwd <state dir>/jobs --kill-grace <jobs.kill_grace> --label ticket=<KEY> --label owner=ticket-work --pass-env <name>... --actor <actor> -- <absolute ticket-work path> _job <work id>`. A `pass_env_undefined` warning cancels the job and runs the restore flow. Without jobsctl the job command runs in the foreground of `start`.
11. **Output.** The start result object. Exit 0.

A `--dry-run` start performs steps 1 to 5 and 7 (reads and dry-runs only), stores nothing, and claims nothing: it uses `ticket-queue claim --dry-run` or `next --claim --dry-run`.

### Claim release rules

- A refusal before step 8, an `unmapped` ticket, a hook veto, a decline, a rejected or expired pending start, and a diverged ticket release with a plain `release` (`ticket-queue release KEY --holder <holder>`).
- A `precondition_failed` from `start --auto` and every failure that follows a landed step (the restore flow) release with `--failed`, so ticket-queue's auto-skip removes a ticket after repeated failures.
- A human `start KEY` that fails a precondition releases plainly.

## Job command

`ticket-work _job WORK_ID` is what the jobsctl job runs. It is not a user command. It is resume-aware: it reads `JOBSCTL_JOB_ID` and `JOBSCTL_ATTEMPT` but decides from its own records. It takes the work item lease and runs these steps:

1. Load the work item; refuse (exit 20) when its phase is not `starting`, `working` or `in_review`.
2. Run the `pre-launch` hooks. A veto restores the start (when no agent exists) and exits 11. An escalation records `job_held: pre_launch`, a pending confirmation of action `launch`, and exits 13 (the job is held with reason `exit_13`).
3. Find the agent. The stored agent id is checked with `agent-spawn show`; when none is stored, `agent-spawn list --label ticket=<KEY> --label owner=ticket-work --label job=<JOBSCTL_JOB_ID> --json` is tried and a candidate is accepted only when its `repo` equals the work item's repository and its worktree branch equals the recorded branch (labels are not authenticated against trusted agents).
4. No agent: `agent-spawn launch --kind implement --mode <mode> --repo <repo> --branch <branch> --base <base> --worktree new --skill <skill> --plugin-dir <bundled plugin> [--plugin-dir <configured>...] --prompt-file <file> [--input-file <file>] --permission-profile <profile> --sandbox <level> --setting-sources <list> --env-allowlist-only <name>... --label ticket=<KEY> --label owner=ticket-work --label repo=<repo> --wait --result-file <file> --json`. A parked agent: `agent-spawn resume <agent_id> --mode <mode> [--prompt-file <file>] --wait --result-file <file> --json`. A live agent: `agent-spawn wait <agent_id>`. The job's lifetime covers the agent run, so the jobsctl queue cap counts it and a `cancel --force` reaches the agent through agent-spawn's cancellation chain.
5. Classify the result by its JSON root (`error` or `agent`) and `phase`. Store the agent id from the result as soon as it is known, and the report.
6. Exit with the agent outcome: 0 `done`, 13 `blocked` or `needs-input`, 14 to 18 passed through. A launch failure (an error envelope, or a result whose `phase` is `launch`) runs the restore flow, fires `post-start-failed`, and exits with the lower exit code (12 when none).

The job command never passes `--yes`, `--force` or `--override-escalation` to any tool. Exit code 13 from agent-spawn means two things (a blocked or needs-input run, or a launch escalation); the result JSON distinguishes them, and a launch escalation records a pending confirmation.

## Sync order

1. **Lease.** Take the sync lease; a held lease exits 0 `already_running`.
2. **Claims.** `ticket-queue claims --holder <holder> --json` gives each claim's `ticket_state`. Claims of work items in phase `pending`, `starting`, `working` or `in_review` are renewed (`claim KEY --renew --holder <holder>`) when the remaining life is below `claim.renew_below` (default one half of the TTL). Claims with no work item and older than `claim.orphan_after` (default 15 minutes) are released plainly (a crash between the claim and the store). A `done`, `gone` or `reassigned` claim state sets `ticket_diverged` and releases the claim plainly; a `moved` claim is renewed with the canonical key and the work item is updated. A refusal `not_held` sets `claim_lost`.
3. **Jobs.** For work items with a job, `jobsctl show --unique-key ticket:<site>:<KEY> --json`. A canceled or vetoed job or a failed job with no agent runs the restore flow (phase `failed`); a held job with reason `exit_13` and a parked agent that reported `blocked` or `needs-input` sets `job_held`; a held job whose agent has since started again is resolved (`jobsctl resolve <id> --as done`).
4. **Agents.** `agent-spawn list --label owner=ticket-work --json` (plus the stored ids): update each work item's agent facts (status, `needs_attention`, last outcome). `blocked` and `escalated` (needs-input) attention raise the event `agent_blocked`; `failed`, `timeout`, `lost` and `unreported` raise `agent_failed`.
5. **Discovery.** For each repository mapped by an active board, `forgectl --json prs --repo <repo id> --author me --state all --updated-since <cursor minus sync.overlap> --limit 1000` (host-wide `--author me` is used instead when a board maps many repositories on one host). The cursor is the newest `updated_at` seen per repository; a result with `complete: false` re-runs narrower (`--state` split) and then records `sync_failed`. An empty list is never evidence that a pull request is absent (see PR linking). Items are matched to work items (PR linking).
6. **Read.** `forgectl --json show <pr>` for every linked, non-ignored pull request whose list item changed, and for every open one at least every `sync.reread_open_after` (default one hour). `exit 10` marks the link `missing` (a deleted pull request or a repository that moved out of reach) and sets nothing else. Facts are compared with the stored last-seen facts to derive events (Status map).
7. **Stale flags.** `pr_idle`, `superseded`, `pr_closed_unmerged` handling (Stale and diverged work).
8. **Rules.** Each event that is new for the work item is evaluated against the board's status map: the rule is applied, recorded as a pending confirmation, or skipped (Status map).
9. **Cleanup.** After `pr_merged`: teardown (Teardown), then release the claim plainly.
10. **Attention and hooks.** Set or clear attention flags, fire hooks, deliver the outbox (Hooks).

Each step records its own failure per work item and continues with the others; a failure of a lower tool for the whole run exits 12.

## Status map

The map is per board, keyed by event name. Every event may have one rule; an event without a rule fires its hooks and does nothing else.

### Events

| Event | Fires when |
|---|---|
| `started` | the start changes were applied (or there were none) |
| `pr_opened` | the first linked pull request is observed open, draft or not |
| `pr_ready` | the first linked pull request is observed open and not a draft |
| `pr_merged` | at least one linked pull request merged and none is still open |
| `pr_closed_unmerged` | every linked pull request is closed and none merged |
| `agent_blocked` | the agent's attention is `blocked` or `escalated` |
| `agent_failed` | the agent's attention is `failed`, `timeout`, `lost` or `unreported` |
| `stopped` | `stop` ran |

A merge while other linked pull requests are open fires `post-status` with `event: pr_merged_partial` and applies no rule. An event is identified by `(work id, event, event key)`; the event key is a hash of the sorted `pr_id` set and states for pull request events and `<agent id>:<run>` for agent events. An applied event is never evaluated again. A rejected pending confirmation marks its event key declined; an expired one does not (the next `sync` creates it again while the event still holds).

### Rule fields

| Field | Meaning |
|---|---|
| `to` | target status name (required; ticketctl chooses the transition by target) |
| `from` | list of status names the ticket must be in; required for `started`; for other events absent means no guard. The live status is checked by ticket-work and passed to ticketctl as `--if-status <live status>` |
| `resolution` | resolution name; required when the target is a done status, else refused at load |
| `assign` | `me`, `none` or an account id (`started` only; `me` assigns when unassigned) |
| `sprint` | `open`, `next` or a numeric sprint id (`started` only) |
| `confirm` | `ask` (default), `auto` or `never` |
| `comment` | `true` posts one fixed-text comment per event (Ticket comments) |

`confirm: auto` applies without asking; only the user's own config can set it, per board and event, and `defaults.confirm` sets the default for rules that give none. `confirm: never` turns the rule off. An enforced gate (the `pre-transition` hook) may also allow an automatic apply (design guide §12). Each applied rule writes the transition through ticketctl (plan with `--dry-run`, `--yes --expect-plan <hash>` after the confirmation, `--actor`, `--decision-id`) and an audit record.

A board without `started.to` or `started.from` refuses `start` and fails `validate`. ticket-work ships no status names; `config.example.yaml` documents the shape with placeholder names.

### Ticket comments

`comment: true` on a rule (or `link_comment: true` on a board, which applies to the `pr_opened` event) posts one comment through `ticketctl comment KEY --body-file <file> --dedupe-key ticket-work:<site>:<KEY>:<event>:<event key hash> --yes --expect-plan <hash>`. The body is fixed text built from trusted data only (the event name and the pull request URL), followed by ticketctl's attribution paragraph for automatic actors. It follows the rule's `confirm` flow like a transition. After `outcome_unknown` it is retried only with the same key. Comments are off by default.

## Stale and diverged work

- `pr_idle`: no activity on any open linked pull request for `sync.pr_idle_after` (default 14 days). Activity is the newer of `updated_at` and the last CI or review change seen in `show`.
- `pr_closed_unmerged`: every linked pull request closed unmerged. The default is to notify only (the rule is absent): no transition and no teardown.
- `superseded`: a newer linked pull request exists for the same work item while an older one is open or closed unmerged.
- `ticket_diverged`: the claim state is `done`, `gone` or `reassigned`. The only automatic action is releasing the claim and stopping tracking (phase unchanged, the flag set); a `moved` claim is renewed with the new key.

Staleness never transitions a ticket, never tears down a worktree and never closes a pull request.

## Preconditions

`boards.<name>.preconditions` is a list of named checks from a closed set; each entry is `{name, check, ...}` and the name appears in refusals.

| Check | Passes when |
|---|---|
| `has_estimate` | `estimate` is a number; `null` with `incomplete: ["estimate"]` fails as unknown |
| `status_in: [..]` | the live status name is in the list (case-insensitive) |
| `assignee: me\|none\|any` | the ticket's assignee matches (`me` is the account id from `ticketctl whoami`) |
| `not_blocked` | `blocked.value` is `false`; `null` fails as unknown |
| `has_parent` | the ticket has a `parent` |
| `in_sprint: open\|any` | the ticket is in an active sprint (`open`) or any sprint |
| `labels_absent: [..]` | none of the labels is present |

Preconditions run at `start` (step 5) and again at `confirm` of a pending start. A value ticketctl reports as unknown fails the check and the refusal says it was unknown. Organization logic that does not fit the set belongs in a `pre-enqueue` hook.

## Ticket to repository and branch

`boards.<name>.repos` is an ordered list of rules `{match: {component, label, project, epic, issue_type}, repo: <repo id>, base: <branch>}`; the first match wins and a rule with an empty `match` is the board default. A ticket that matches nothing is refused with `unmapped`. A `repos.<id>` override entry (per-repository settings) takes the per-repository position in the precedence order.

The branch is `<type>/<KEY>-<slug>`. `type` comes from `boards.<name>.branch.types` by issue type (default `feat`). The slug is derived from the title by one rule: NFKD-normalized, ASCII only, lower-case, runs of other characters become one `-`, trimmed, at most 40 characters, `ticket` when empty. No other ticket text reaches the branch. ticket-work passes `--branch` and `--base` to agent-spawn. The key always appears as a whole token, which keeps tier-two linking reliable.

## PR linking

Every link has a `tier`; linking never relies on the agent's claim alone.

| Tier | Evidence | Effect |
|---|---|---|
| `claimed` | the agent's artifact `prs[].url` (or a `pr=` label) names a pull request that forgectl `show` confirms: authored by the user's account, in a repository the board maps, with the head branch ticket-work launched | linked automatically |
| `branch` | the whole-token key in `head.ref`, case-insensitive, with the key taken from the ticket (never a generic pattern), for a pull request authored by the user in a mapped repository | linked automatically |
| `title` | the key only in the title | recorded as `candidate`; fires `post-attention` (`candidate_link`); never moves the ticket until `link` |
| `manual` | `ticket-work link` | linked |

- The key matches `head.ref` with `(?<![A-Za-z0-9])KEY(?![A-Za-z0-9])` (case-insensitive, `KEY` escaped).
- A link stores `pr_id` and `repo_id` (never the display string, which a repository rename changes), the tier, the time and the last-seen facts (`state`, `draft`, `head.sha`, `merged_head_sha`, `updated_at`).
- One ticket may have several links (stacked pull requests, follow-ups, one per repository).
- A pull request linked to one work item is never linked to another automatically (`linked_elsewhere`).
- `prs --repo` for a missing or renamed repository returns exit 0, an empty list and `complete: true`; `show` returns exit 10. An empty list is never read as "no pull requests": a link is marked `missing` only by a `show` exit 10.
- Discovery uses the cheap `prs` list; `merged_head_sha`, `merged_at` and `closed_at` need one `show`.

## Pending confirmations

A pending record has `id` (`^pd-[a-z2-7]{8}$`), `tool: ticket-work`, `action`, `target` (the work id), `created`, `summary`, `expires`, `actor`, `plan_sha256` (map of step to hash), `rule`, `event`, `escalated_by`, `status` (`open`, `confirmed`, `rejected`, `expired`) and `details`. `action` is `start`, `transition`, `comment`, `launch` or `stop`. Records never contain ticket text.

- `start` pending: created by a non-TTY start, an escalated `pre-enqueue` hook. It holds the claim (renewed by `sync`). `pending.start_expiry` defaults to 24 hours. `confirm` re-checks the claim live (a refused renewal exits 20 `claim_lost`), re-evaluates the preconditions, re-runs the other `pre-` hooks (overriding only the escalating hook), re-plans with `--dry-run` and continues from Start order step 8's apply. `reject`, expiry and a diverged ticket release the claim plainly. A `confirm` after expiry exits 20 (`expired`).
- `transition` and `comment` pending: created by a non-TTY `sync` for a rule whose `confirm` is `ask`, keyed by work id, event and the pull request set so a repeated `sync` never duplicates it. `confirm` re-plans with `ticketctl ... --dry-run`, then applies with `--yes --expect-plan <hash>` (a stale plan becomes a new pending record and exits 13). Expires after `pending.expiry` (default 7 days); expiry drops the record only.
- `launch` pending: created when a `pre-launch` hook escalated in the job. `confirm` re-runs the other `pre-` hooks and continues the held job with `jobsctl retry <id> --attempt N`.
- `stop` pending: created when the `stopped` rule needs confirmation.
- `confirm` and `reject` exit codes: 0; 10 no such record; 20 `expired`, `not_pending`, `claim_lost`, `precondition_failed`, `stale_plan` (a new record was created); 13 a hook escalated again; 11 a hook vetoed; 2 `human_only`.

A human declining ticketctl's own prompt is exit 20 `declined` and is never stored as pending.

## Restore

The restore flow undoes a start whose agent never launched. The previous status, assignee and sprint ids are recorded before the start applies anything.

1. `ticketctl transition KEY --to <previous status> --if-status <started status> --dry-run`, then applied with `--yes --expect-plan <hash>`, when the start changed the status.
2. `ticketctl update KEY --assign none|<previous>` when the start assigned the ticket.
3. `ticketctl sprint add KEY --sprint <previous id>` for a previous open or future sprint, or `sprint remove KEY` when there was none and the start added one. A closed previous sprint cannot be restored.
4. Release the claim with `--failed`, set phase `failed`, fire `post-start-failed` with the result.

`precondition_failed` on step 1 means a human moved the ticket: leave it alone. `no_such_transition` or a closed sprint sets `needs_attention: restore_failed` with the details. The flow never retries by guessing another route and skips `pre-` hooks (so a gate cannot leave the ticket in the wrong state); it is audited. `restore_on_failure: false`, or a board with no `started.to`, leaves the ticket as it is. The flow is idempotent and may run from the job command and from `sync`; the work item's `restore_state` (`none`, `done`, `failed`) prevents repeats.

## Teardown

After `pr_merged`, for each agent of the work item that is not live: `agent-spawn teardown <agent_id> --merged-head <merged_head_sha of the last merged pull request> --actor auto:ticket-work --decision-id ...`. A torn-down agent (exit 10 with `details.status: torn_down`) counts as done. A refusal (`dirty`, `unpushed`, `in_use`, `repo_config_changed`, `held`, `live`, `partial`) sets `teardown_refused` with the lower reason and is retried on the next `sync`; `--force` is human-only and ticket-work never passes it. After teardown succeeds the claim is released plainly and `cleanup.teardown` is `done`. `cleanup.teardown: false` in config skips teardown. A closed-unmerged work item is never torn down automatically.

## Slot contract

Skill slot `implement-ticket` (architecture §5.5): default skill `ticket-work:implement-ticket`, kind `implement`, default mode interactive.

- **Bundle.** The plugin `ticket-work` ships inside the package and is located with `importlib.resources.files('ticket_work') / 'plugin'`. It contains the skill, a reference file holding the skill marker, the four sandbox placeholder entries (`.claude/`, `.mcp.json`, `CLAUDE.md`, `CLAUDE.local.md`), and the bundled permission profile. The profile sets no permission mode and allows file edits inside the working directory only (`Edit(/${CWD}/**)`, `Write(/${CWD}/**)`, never a bare tool name), `git` and `gh` through Bash, and the read tools; other tools prompt the human (the interactive default). `agent.skill` and `agent.plugin_dirs` replace or add skills.
- **Kind and trust.** ticket-work always passes `--kind implement` and verifies that the launch result's `run_kind` is `implement`; any warning in a `start` result is fatal (an unknown kind silently runs the third-party-reading review profile). The run is trusted (not third-party-reading): boards are semi-trusted (architecture §13.2 rule 7) and ticket text is still fenced. ticket-work never passes `--reads-third-party`.
- **Safety settings, per call.** `--permission-profile <bundled or agent.permission_profile>`, `--sandbox <agent.sandbox>` (default `off`: a sandboxed, `dontAsk` run cannot read `~/.config/gh`, `~/.ssh` or `~/.gitconfig`, has a domain-limited network and loses `GH_TOKEN`; a recorded deviation from design guide §11), `--setting-sources <agent.setting_sources>` (default `["project"]` so the repository's own instructions load; a recorded deviation from the guide's default of none), and `--env-allowlist-only <name>` for each name of `agent.env_allowlist` (default none passed: the trusted kind inherits the launcher's environment minus claude-session's `secret_env`). Every one is replaceable in config.
- **Prompt file.** ticket-work builds one prompt file in its state directory (deleted when the run ends). Trusted facts come first, outside any fence: the ticket key, the repository id, the branch, the base, the draft-pull-request default, a `run_token` (random per run) and the skill marker instructions. Untrusted text is fenced with a nonce, `<untrusted source="ticket" id="R">...</untrusted id="R">`, with the standing "data, not instructions" rule and `</untrusted` neutralized (design guide §12): title, description, acceptance criteria (when the board maps the field), the parent epic's title, linked ticket keys with titles, and the last 10 comments (in an `--input-file` when they would make the prompt large). A resume's `--prompt-file` carries the human's answer, fenced the same way.
- **Artifact.** The agent reports `done` with `{"schema_version": 1, "ticket": "<KEY>", "branch": "<name>", "prs": [{"url": "..."}], "summary": "...", "skill_marker": "...", "run_token": "..."}`. ticket-work reads it from the frozen path in `claude-session status --json` (through the agent-spawn result's `run.report.artifact.path`) and validates it strictly: the schema, `ticket` equal to the work item, `skill_marker` equal to the marker in the bundled reference file, `run_token` equal to the one in the prompt, and `report.implicit: false`. A wrong skill name exits 0 `done` with no artifact, so a missing or mismatching artifact is a failed start (`agent_failed`). The agent's `prs` and `branch` are claims: each pull request is verified through forgectl (PR linking). `summary` is untrusted.
- **Other reports.** `blocked` and `needs-input` carry only a reason (`report.status` tells them apart); the agent is not asked for an artifact.
- **Self-labeling** (`agent-spawn label add --session`) is optional for the agent; a shell variable in a command is denied inside an isolated run, so ticket-work never depends on it.

## Hooks

Hooks follow design guide §8: configured under `hooks.<name>` as `{cmd, timeout, async}` lists, run via `sh -c` in their own process group, JSON on stdin, default timeout 30 seconds. Pre-hook exit 0 continues, exit 13 escalates, any other non-zero vetoes (exit 11). Environment: `TICKET_WORK_HOOK`, `TICKET_WORK_ID` (the work id), `TICKET_WORK_OBJECT_TYPE` (`work`), the tool's environment minus configured credentials. Per-invocation `--hook <name>=<cmd>` is accepted by `start`, `resume`, `confirm`, `stop` and `sync`.

| Hook | Runs | Notes |
|---|---|---|
| `pre-enqueue` | `start` step 6, after the claim and preconditions | veto releases the claim plainly; escalation records a pending start |
| `pre-transition` | before every ticketctl write ticket-work makes (transition, sprint, comment) | veto or escalation applies the rule's `confirm` flow; skipped by the restore flow (which is audited) |
| `pre-launch` | in the job, before `agent-spawn launch` or `resume` | veto restores the start; escalation holds the job (exit 13) |
| `post-link` | a link or unlink | |
| `post-status` | an event was applied, recorded as pending, or skipped, including `pr_merged_partial` | |
| `post-start-failed` | a start was restored | |
| `post-pending` | a pending confirmation was recorded | |
| `post-attention` | an attention flag was set | closed `reason` (Attention reasons) |

Payload (schemas in `schemas/hooks/`): `tool`, `hook`, `event_id` (post hooks), `object_type: work`, `object_id`, `repo` (the work item's repository id), `labels` (`ticket=<KEY>`, `owner=ticket-work`, `board=<name>`), `board`, `site`, `key`, `phase`, `actor`, plus per hook: `event`, `rule`, `plan` (for `pre-transition`: `action`, `steps`, `current_status`, `target_status`, `plan_sha256`), `pending_id`, `reason`, `pr_ids`. Payloads carry keys, ids, `phase`, enums and counts, never ticket, pull request or model text. Post hooks are delivered at least once through an outbox, after the command prints its result, with `event_id`; a failed post hook is logged and never fatal.

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

Refusal reasons (exit 20): `live`, `precondition_failed`, `unmapped`, `already_started`, `not_active`, `claimed`, `not_in_pool`, `claim_lost`, `declined`, `expired`, `not_pending`, `stale_plan`, `not_linkable`, `already_linked`, `holder_mismatch`, and the reasons of a lower tool passed through (`details.lower_error`). Exit 22 means "nothing to do" here, not invalid input (ticketctl's meaning).

## Output by exit code and error envelope

With `--json`: exit 0 and 22 print the command's object; 13 prints the pending object (or the held result); 2, 10, 11, 12, 20 and 21 print the error envelope `{"error": {"code", "message", "reason", "details", "tool", "lower_code", "lower_error", "hook", "hook_stderr", "decision_ids"}}`. `tool` names the lower tool that failed (`ticketctl`, `ticket-queue`, `forgectl`, `agent-spawn`, `jobsctl`, `wtctl`); `lower_error` is its whole `error` object verbatim and untrusted. Errors go to stderr as well.

## Objects

- **Work item** (`schemas/cli/show.json`, summary in `list.json`): `id`, `site`, `key`, `requested_keys`, `board`, `title` (untrusted), `phase`, `needs_attention`, `attention_detail`, `repo`, `branch`, `base`, `holder`, `claim` (`expires_at`, `renewed_at`, `state`), `previous` (`status`, `assignee`, `sprint_ids`), `started_status`, `job` (`id`, `status`), `agent` (`id`, `status`, `needs_attention`), `links`, `pending` (ids), `cleanup`, `restore_state`, `last_report` (`status`, `summary` untrusted), `created`, `updated`.
- **Link**: `pr_id`, `repo_id`, `pr`, `tier` (`claimed`, `branch`, `title`, `manual`), `state` (`linked`, `candidate`, `ignored`, `missing`), `facts` (`state`, `draft`, `head_sha`, `merged_head_sha`, `updated_at`), `linked_at`.
- **Start result**: `work`, `claim`, `plans`, `applied` (step list with `status`), `pending`, `job`, `warnings`, `dry_run`.
- **Sync report**: `items` (per work item: `id`, `phase`, `events`, `applied`, `pending`, `errors`), `claims_released`, `already_running`, `partial`, `errors`.
- **Pending record**: Pending confirmations.

## Configuration

`~/.config/ticket-work/config.yaml` plus `config.d/*.yaml` (design guide §5), validated at load (`schemas/config.json`, `config.example.yaml`). Precedence: flags, `repos.<id>`, environment, global config, defaults. The board takes the per-repository position when a board setting applies.

| Key | Default | Meaning |
|---|---|---|
| `me.name` | OS user | actor name |
| `instance` | sanitized hostname | part of the claim holder `ticket-work:<instance>` |
| `boards.<name>.site` | none (required) | the ticketctl site |
| `boards.<name>.repos` | none (required) | ordered repository rules |
| `boards.<name>.branch.types` | `{default: feat}` | branch type by issue type |
| `boards.<name>.preconditions` | `[]` | named checks |
| `boards.<name>.status_map` | `{}` (`started` required to start) | event rules |
| `boards.<name>.link_comment` | `false` | comment on `pr_opened` |
| `defaults.confirm` | `ask` | default for a rule's `confirm` |
| `start.max_pending` | `1` | unresolved pending starts allowed under `--auto` |
| `pending.start_expiry` | `24h` | pending start lifetime |
| `pending.expiry` | `7d` | other pending lifetime |
| `claim.ttl` | ticket-queue's default | passed with `--ttl` when set |
| `claim.renew_below` | `0.5` | renew when this fraction of the TTL remains |
| `claim.orphan_after` | `15m` | release a holder's claim with no work item |
| `sync.overlap` | `1h` | discovery watermark overlap |
| `sync.reread_open_after` | `1h` | re-read open pull requests at least this often |
| `sync.pr_idle_after` | `14d` | `pr_idle` threshold |
| `pr_watch.enabled` | `false` | use pr-watch events as an early trigger |
| `agent.skill` | `ticket-work:implement-ticket` | the slot skill |
| `agent.mode` | `interactive` | `interactive` or `headless` |
| `agent.sandbox` | `off` | `off`, `preferred` or `required` |
| `agent.permission_profile` | bundled file | replaces the bundled profile |
| `agent.setting_sources` | `["project"]` | Claude setting sources |
| `agent.env_allowlist` | `[]` | `--env-allowlist-only` names |
| `agent.plugin_dirs` | `[]` | extra plugin directories |
| `agent.model` | none | passed with `--model` when set |
| `jobs.enabled` | `true` | use jobsctl |
| `jobs.queue` | `tickets` | jobsctl queue |
| `jobs.pass_env` | `[]` | `--pass-env` names (credentials come from jobsctl's env file) |
| `jobs.kill_grace` | `120s` | `--kill-grace` |
| `jobs.max_running` | `3` | cap without jobsctl |
| `cleanup.teardown` | `true` | tear down after `pr_merged` |
| `restore_on_failure` | `true` | run the restore flow |
| `retention.work` | `90d` | `prune` age |
| `retention.pending` | `30d` | `prune` age for resolved pending records |
| `hooks.<name>` | `[]` | hook lists |
| `tools.<name>` | the tool's name | executable path per sibling |

## Environment variables

Config scalars may be set as `TICKET_WORK_<KEY>` (nested keys joined with `__`). Structured config (boards, hooks, rules) cannot be set from the environment. ticket-work reads no credentials: each sibling tool reads its own, and the job receives the names in `jobs.pass_env` from jobsctl's env file. `XDG_CONFIG_HOME` and `XDG_STATE_HOME` redirect config and state.

## Labels

ticket-work labels the agent and the job: `ticket=<KEY>`, `owner=ticket-work`, `repo=<repo id>`. It adds `pr=<host/path#N>` when a link is made. Labels are not authenticated against trusted agents, so ticket-work verifies every link against forgectl and every agent against its own records before an external action.

## Files

`~/.local/state/ticket-work/`: `state.db` (private), `audit.jsonl` and `log.jsonl` (public append-only contracts, `schemas/audit.json` and `schemas/log.json`), `prompts/` (prompt files, deleted when the run ends), `jobs/` (the job's cwd). Schema migrations are additive.

## Audit and log

Every external action appends an `attempted` record before the write and an outcome record after it (pairs share `attempt_id`): `transition`, `sprint_add`, `comment`, `restore`, `link`, `unlink`, `launch`, `resume`, `teardown`, and the pending confirmations (`pending_confirm`, `pending_reject`, `pending_expire`). Fields: `ts`, `actor`, `decision_id`, `target` (work id), `action`, `inputs` (`work_id`, `event`, `rule`, `plan_sha256`, `pr_id`), `result`. The attribution of an agent's own commits and pull requests is the implement skill's job (commit trailers and the pull request body).

## Concurrency

Every command that contacts other tools or the store for writing takes a lease (design guide §4.3): one `sync` lease and one lease per work item, each with holder PID, process start time and expiry, renewed by a heartbeat while the holder lives. A second `sync` exits 0 with `already_running: true`. Job commands take the work item lease; a held lease makes `_job` exit 20 (`live`) without touching anything.

## Dependencies

| Tool | Binding | Used for |
|---|---|---|
| ticketctl | A | ticket reads, transitions, sprints, comments, restore |
| ticket-queue | A | `next --claim`, `claim`, `claims`, `release` |
| forgectl | A | pull request discovery and state (minimum 0.52.0) |
| agent-spawn | A | launch, resume, wait, label, teardown |
| jobsctl | A (optional) | the `tickets` queue, capacity |
| wtctl | A | `wtctl locate` before a start |
| pr-watch | A (optional) | early-detection trigger |

A missing required tool is exit 12 `tool_missing` naming its install command. The minimum versions of the siblings that implement their designed interfaces are pinned when implementation starts.

## Upgrades

The `schema_version` of `state.db` is additive-only. A newer database than the tool exits 12 (`schema_newer`). Hook payloads and `--json` outputs ignore unknown keys.

## Residual risks

- Two machines with separate stores can both pass the start checks in the same second; Jira's live status check and `--if-status` make the second transition `unchanged`. There is no cross-machine lock.
- Labels and an agent's artifact are claims; verification relies on forgectl and ticket-work's own records.
- A trusted, unsandboxed implement agent can run any command the user can; the bundled profile only guides it.
- ticketctl's confirmation prompt is not a boundary against a caller that can allocate a pty (architecture §13.1).
- `plan_sha256` has no expiry; ticket-work's pending expiry bounds the window.
- A `start` whose Jira changes landed and whose enqueue then crashed is repaired by the next `sync` (the work item's phase `starting` with no job runs the restore flow).

## Platform notes

Linux, WSL and macOS. tmux is needed only for interactive agents (through agent-spawn); `--mode headless` needs none.
