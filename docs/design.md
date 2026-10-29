# ticket-work: design

Status: Seeded from awkit architecture v1.4; not yet designed.

Section references (§N) point to `../awkit-docs/architecture.md` unless marked "design guide" (`../awkit-docs/design-guide.md`).

## Role and layer

Own the lifecycle of a worked ticket: claim, transition, launch an implement agent, link the PR, and follow it to done.

Layer 3 (workflow). Must work fully standalone; no upward awareness.

Skill-wrapper tool (§5.5, design guide §11). Default slot: `implement-ticket` (bundled as `ticket-work:implement-ticket` in `plugin/`).

## Responsibilities

From §5.3 (`ticket-work`), verbatim:

Owns the lifecycle of a worked ticket (QR-16).

- Commands: `start [KEY] [--auto] [--skill ...] [--mode ...]`, `sync`, `list`, `stop <KEY>`, `pending`, `confirm <id>`, `reject <id>`.
- Uses: ticketctl, ticket-queue, forgectl, pr-watch, agent-spawn, wtctl, jobsctl.
- Notes:
  - `start` with no key takes `ticket-queue next --claim`; with a key it runs `ticket-queue claim KEY`.
  - **Transitions are applied at confirm time.** From a TTY, `start` shows and confirms the assignment, sprint and transition, applies them (`ticketctl ... --yes`), then enqueues. A non-interactive `start` (e.g. `--auto` from cron) records a pending confirmation and does not enqueue; `confirm <id>` applies the changes and enqueues. Setting `auto_transition: true` in config removes the confirmation. `start --auto` enqueues only while `jobsctl capacity` is above 0, counts unresolved pending starts against that capacity, and records at most one pending start at a time (unless `auto_transition: true`).
  - Jobs use queue `tickets` and `--unique-key ticket:<KEY>`. The resume-aware job command launches an interactive implement agent (kind `implement`) labeled `ticket=KEY` and `owner=ticket-work`. If the job fails to launch the agent, ticket-work restores the previous ticket status, releases the claim with `--failed`, and fires `post-start-failed`.
  - `sync` renews the claims of in-flight tickets and releases them when work ends. It links PRs to tickets (section 20), adds the `pr=` label via `agent-spawn label add`, adds a pr-watch watch (`--owner ticket-work`), writes an audit entry, and applies the per-board **status map** to events `pr_opened` (including draft), `pr_ready`, `pr_merged`, `pr_closed_unmerged`, `agent_blocked`, `agent_failed`. Every run checks the current state of linked PRs via forgectl; `pr-watch events --since <own cursor>` provides early detection. Closed-unmerged default: notify, no transition, no teardown. `sync` also resolves held ticket jobs; the agent itself continues through `agent-spawn resume`.
  - `stop <KEY>` exits 20 (`reason: live`) if the agent is live (it never ends a live session). Otherwise it leaves the agent parked and the worktree in place, releases the claim, and applies an optional transition per the status map. Removing the worktree is a separate teardown (`agent-spawn teardown`; a human passes `--force` if the work is unmerged).
  - Organization rules (e.g. "needs story points to leave backlog") are per-board preconditions in config. Fully standalone via cron; the harness only triggers `sync` early.
  - Hooks (indicative): `pre-enqueue`, `pre-transition`, `pre-launch`, `post-link`, `post-status`, `post-start-failed`, `post-pending`.

## Uses

- `ticketctl` (ticket reads and transitions); binding: TBD (A/B/C), decided in this tool's design session
- `ticket-queue` (next/claim/release); binding: TBD (A/B/C), decided in this tool's design session
- `forgectl` (PR state and linking); binding: TBD (A/B/C), decided in this tool's design session
- `pr-watch` (PR watches and early event detection); binding: TBD (A/B/C), decided in this tool's design session
- `agent-spawn` (launches and labels implement agents; teardown); binding: TBD (A/B/C), decided in this tool's design session
- `wtctl` (repo resolution and worktrees); binding: TBD (A/B/C), decided in this tool's design session
- `jobsctl` (ticket job queue and capacity); binding: TBD (A/B/C), decided in this tool's design session

## Key flow: §10.2 Ticket work (flow B)

Verbatim from the architecture:

1. `ticket-work start` (or `start --auto` from cron, only while `jobsctl capacity` is above 0, counting unresolved pending starts) → `ticket-queue next --claim`, or `ticket-queue claim KEY` for an explicit key.
2. `pre-enqueue` hooks run (may veto, or escalate with exit 13, e.g. a gate).
3. From a TTY, ticket-work shows and confirms the assignment, sprint and transition (public default) and applies them with `ticketctl ... --yes`. Without a TTY it records a pending confirmation (`post-pending`) and stops (section 12.4); `confirm <id>` applies them and continues.
4. It enqueues a jobsctl job (queue `tickets`, `--unique-key ticket:<KEY>`) running its internal, resume-aware job command.
5. The job runs `agent-spawn launch --kind implement --mode interactive --repo <repo-id> --branch <branch> --worktree new --skill ticket-work:implement-ticket --plugin-dir <bundled> --permission-profile <bundled file> --env-allowlist-only <vars> --label ticket=KEY --label owner=ticket-work --wait`: wtctl resolves the clone and creates the worktree, termctl opens window `KEY` in the shared session, claude-session starts Claude with notes context. If the launch fails, ticket-work restores the previous status, releases the claim with `--failed`, and fires `post-start-failed`.
6. The agent brainstorms with you, implements (including in-repo doc updates), pushes, opens a draft PR (the implement skill enforces the draft default), may record `pr=...` via `agent-spawn label add --session $CSESSION_ID`, and reports done. `exec` auto-exits the session, `supervise` parks the agent and exits, the window closes and the job ends.
7. `ticket-work sync` (cron, or early via the harness on pr-watch changes) is the guaranteed linking path: it renews the claim, links the PR, adds the `pr=` label, adds a pr-watch watch, writes an audit entry, checks the PR's current state via forgectl, and applies the status map: `pr_opened` → testing status; `pr_merged` → done (with resolution), then `agent-spawn teardown --merged-head <sha>` and release of the claim.

## Relevant cross-cutting sections

- §3.2, §3.3: layering rules and edge bindings
- §5.5: capability slots: `implement-ticket`, kind `implement`
- §9: agent lifecycle, supervision, teardown (agent-spawn)
- §10.2: ticket work flow (flow B)
- §11: ticket ranking and claims (ticket-queue)
- §12: autonomy and gates: public defaults (§12.1), pending confirmations and `--yes` (§12.4)
- §13: security: trust tiers for tickets (§13.2 rule 7), credentials
- §14: audit: PR linking entries, attribution
- design guide §4.3, §4.4, §11: concurrency and cron; confirmations; skill-wrapper pattern

## Constraints (decided)

From §20 (`ticket-work`):

ticket → repo mapping via config (`boards.<b>.repo` or a component map, giving a repo id that wtctl resolves). PR linking matches the ticket key as a whole token in branch names and searches PRs authored by the user in repos mapped to the board.

Packaging: The bundled plugin is shipped inside the package and located via `importlib.resources.files('ticket_work') / 'plugin'`.

## Open topics

From §20 (`ticket-work`):

status map format, preconditions, stale PR handling, ticket state machine.

## Decisions

| Decision | Rationale | Date |
|---|---|---|

## Questions for the design session

1. What is the per-board status map format, and how are events mapped to transitions?
2. Which preconditions exist, how are they expressed per board, and when are they checked?
3. How are stale PRs handled (abandoned, superseded, long-lived drafts)?
4. What is the ticket state machine inside ticket-work, and how is it persisted?
