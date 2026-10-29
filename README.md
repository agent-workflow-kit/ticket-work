# ticket-work

Own the lifecycle of a worked ticket: claim, transition, launch an implement agent, link the PR, and follow it to done.

## Status

Pre-design: interface not yet specified; see docs/design.md.

## Layer

L3 (workflow)

## What it does

- `start` claims the next ranked ticket (or a given key) from ticket-queue, confirms assignment, sprint and transition (from a TTY, or as a pending confirmation), and enqueues a job.
- The job launches an interactive implement agent (kind `implement`) in a new worktree via agent-spawn, labeled with the ticket.
- `sync` renews claims, links PRs to tickets, adds watches and labels, writes audit entries and applies a per-board status map to PR and agent events.
- `stop` releases the claim without ending a live session; teardown is separate.
- Organization rules are per-board preconditions in config; fully standalone via cron.

## Indicative commands

Indicative, finalized in `docs/interface.md`.

```text
ticket-work start [KEY] [--auto] [--skill ...] [--mode ...]
ticket-work sync
ticket-work list
ticket-work stop <KEY>
ticket-work pending
ticket-work confirm <id>
ticket-work reject <id>
```

## Dependencies

- `ticketctl` (ticket reads and transitions); binding: TBD (A/B/C), decided in this tool's design session
- `ticket-queue` (next/claim/release); binding: TBD (A/B/C), decided in this tool's design session
- `forgectl` (PR state and linking); binding: TBD (A/B/C), decided in this tool's design session
- `pr-watch` (PR watches and early event detection); binding: TBD (A/B/C), decided in this tool's design session
- `agent-spawn` (launches and labels implement agents; teardown); binding: TBD (A/B/C), decided in this tool's design session
- `wtctl` (repo resolution and worktrees); binding: TBD (A/B/C), decided in this tool's design session
- `jobsctl` (ticket job queue and capacity); binding: TBD (A/B/C), decided in this tool's design session

## Install

```sh
uv tool install git+https://github.com/agent-workflow-kit/ticket-work
```

## Documentation

- System architecture: [`../awkit-docs/architecture.md`](../awkit-docs/architecture.md) ([published](https://github.com/agent-workflow-kit/awkit-docs/blob/main/architecture.md))
- Tool design guide: [`../awkit-docs/design-guide.md`](../awkit-docs/design-guide.md) ([published](https://github.com/agent-workflow-kit/awkit-docs/blob/main/design-guide.md))
- This tool's design: [`docs/design.md`](docs/design.md)
- This tool's interface: [`docs/interface.md`](docs/interface.md)

## License

MIT — see LICENSE.
