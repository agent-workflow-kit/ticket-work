# ticket-work

Own the lifecycle of a worked ticket: claim it, apply the board's start changes after a confirmation, launch an implement agent in its own worktree, link the agent's pull requests to the ticket, apply a per-board status map as they move, and tear the work down after the merge.

## Status

Designed (interface 0.1.0-design); not yet implemented. The normative rules are in [`docs/interface.md`](docs/interface.md).

## Layer

L3 (workflow). A skill-wrapper tool for the `implement-ticket` slot. It works standalone at a terminal and from cron.

## What it does

- `start` claims the next ranked ticket (or a given key) from ticket-queue, checks the board's preconditions, shows and confirms the assignment, sprint and status change (or records a pending confirmation when no human is present), and enqueues a job.
- The job launches an interactive implement agent (kind `implement`) in a new worktree through agent-spawn, labeled with the ticket. The agent opens a draft pull request itself.
- `sync` renews claims (and re-takes a lapsed one), repairs interrupted starts, finds and links the ticket's pull requests (with a recorded evidence tier), derives events from their state and applies the board's status map, tears the work down after the merge and releases the claim.
- `resume`, `stop`, `link` and `unlink` steer a work item; `pending`, `confirm` and `reject` handle confirmations.
- Organization rules (status names, resolutions, "needs an estimate to start") live in the user's config as per-board status maps and preconditions. Nothing organization-specific ships in this repository.

## Commands

```text
ticket-work start [KEY] [--auto] [--board B] [--skill S] [--mode M] [--sandbox L] [--dry-run]
ticket-work resume KEY [--mode M] [--prompt-file F]
ticket-work sync [KEY]
ticket-work list | show KEY
ticket-work stop KEY
ticket-work link KEY PR | unlink KEY PR
ticket-work pending | confirm ID | reject ID
ticket-work cron install|uninstall | export | prune | validate
```

Every command that outputs data supports `--json`. The full surface, exit codes and the order of each flow are in the interface document.

## Safe defaults

Starting a ticket is manual. Ticket status changes are shown and confirmed (a non-interactive run records a pending confirmation). Staleness never moves a ticket or removes a worktree. The agent opens draft pull requests only. The implement agent runs as a trusted session with the sandbox off by default; every safety setting is a config key. Unattended runs (`start --auto`, `--mode headless`) start only tickets from a trusted reporter and read only comments of trusted authors.

## Dependencies

| Tool | Binding | Role | Install |
|---|---|---|---|
| ticketctl | A (hard) | ticket reads and writes | `uv tool install git+https://github.com/agent-workflow-kit/ticketctl` |
| ticket-queue | A (hard) | which ticket next; claims | `uv tool install git+https://github.com/agent-workflow-kit/ticket-queue` |
| forgectl | A (hard) | pull request discovery and state | `uv tool install git+https://github.com/agent-workflow-kit/forgectl` |
| agent-spawn | A (hard) | launches, resumes and tears down agents | `uv tool install git+https://github.com/agent-workflow-kit/agent-spawn` |
| wtctl | A (hard) | repository check before a start, agent adoption | `uv tool install git+https://github.com/agent-workflow-kit/wtctl` |
| jobsctl | A (required for `start --auto`, optional otherwise) | the `tickets` job queue | `uv tool install git+https://github.com/agent-workflow-kit/jobsctl` |

A missing required tool is a clear error naming its install command.

## Install

```sh
uv tool install git+https://github.com/agent-workflow-kit/ticket-work
```

## Configuration

`~/.config/ticket-work/config.yaml` plus `config.d/*.yaml`; see `config.example.yaml` for every key. State lives under `~/.local/state/ticket-work/`. ticket-work holds no credentials: each sibling tool reads its own, and a job receives the variable names listed in `jobs.pass_env` from jobsctl's env file for ticket-work's own tool calls. The agent gets a fixed environment base plus the names in `agent.env_allowlist` only; `jobs.pass_env` names never reach the agent, so a variable the agent needs is listed in both.

## Exit codes

Reserved codes follow the design guide (0, 1, 2, 10 to 13, 14 to 18, 20, 21). Tool-specific: 22 means `start` found nothing to start (reasons `empty`, `no_capacity`, `pending_exists`). Refusal reasons are listed in the interface.

## Documentation

- System architecture: [`../awkit-docs/architecture.md`](../awkit-docs/architecture.md) ([published](https://github.com/agent-workflow-kit/awkit-docs/blob/main/architecture.md))
- Tool design guide: [`../awkit-docs/design-guide.md`](../awkit-docs/design-guide.md) ([published](https://github.com/agent-workflow-kit/awkit-docs/blob/main/design-guide.md))
- This tool's design: [`docs/design.md`](docs/design.md)
- This tool's interface: [`docs/interface.md`](docs/interface.md)

## License

MIT, see LICENSE.
