---
title: Check a PR review bot's thread rules before running the CE feedback loop next to it
date: 2026-10-01
category: workflow-issues
module: pull-request review workflow
problem_type: workflow_issue
component: development_workflow
severity: medium
applies_when:
  - Enabling or widening a PR review bot while ce-babysit-pr and ce-resolve-pr-feedback handle review feedback
  - Re-enabling Greptile's review triggers on pururu (it is installed, and its one trigger rule currently matches nothing)
  - A review bot reads a resolved thread as dismissed, or withdraws a finding on a reply from the repo owner's login
  - A review bot does not re-review on push (no synchronize trigger, or a label-gated re-review)
  - Keeping review rules in a file that ce-code-review does not read
retire_when: "Compound Engineering's ce-resolve-pr-feedback stops replying through the local gh login and resolving the threads it declines, or the bot in question re-reviews every push and keeps resolved or owner-replied findings open; check the installed plugin's skills/ce-resolve-pr-feedback/references/full-mode.md and the bot's trigger and thread rules"
tags: [code-review, review-bot, ce-babysit-pr, ce-resolve-pr-feedback, greptile, github-actions, review-threads, compound-engineering]
---

# Check a PR review bot's thread rules before running the CE feedback loop next to it

## Context

pururu had a CI review bot: `.github/workflows/claude-code-review.yml`, which ran Claude with the instructions in `.claude/review/review.md` (plus `.claude/review/rules.md` and the `review-reader` subagent). Then the maintainer adopted the Compound Engineering (CE) flow. In that flow, `ce-commit-push-pr` hands every new PR to `ce-babysit-pr`, and babysit passes review feedback to `ce-resolve-pr-feedback`. The handoff is on by default: babysit is off only when `auto_babysit` is exactly `false` (compound-engineering 3.30.1: `skills/ce-commit-push-pr/references/apply-and-handoff.md:37-39`).

The bot was built for one human owner who reads every finding. The CE loop is an agent that replies and resolves threads with the owner's `gh` login. The bot read those agent actions as the owner's decisions, so the two together closed findings nobody had read. PR #73 deleted the bot's four files and kept `.github/workflows/claude.yml` (the `@claude` assistant). PR #73 was still open, not merged, when this was written, so the bot's files are still on `origin/main`.

Paths under `skills/` below are in the Compound Engineering plugin (version 3.30.1), not in this repo.

## Guidance

Before you run `ce-babysit-pr` / `ce-resolve-pr-feedback` on a repo that has a review bot, check these five behaviors. Each one either breaks the loop or lets an agent close a finding for good.

1. **Does a resolved thread mean "dismissed"?** `ce-resolve-pr-feedback` resolves every thread it handles except `needs-human`. That includes the reply-list verdicts `not-addressing` and `declined` (compound-engineering 3.30.1: `skills/ce-resolve-pr-feedback/references/full-mode.md:84`, `:174`, `:226-229`). If the bot never re-raises a resolved thread, one agent disagreement ends that finding for good.
2. **Does an owner reply withdraw a finding?** The resolver posts its replies through the local `gh` login, which is the owner's account (the skill runs `Bash(gh *)`, `skills/ce-resolve-pr-feedback/SKILL.md:5`). A bot that trusts "the owner's reply" reads the agent's reasoning as the owner's.
3. **Does the bot read top-level replies?** Findings that live only in a summary comment have no thread to resolve, so the resolver answers them with a top-level PR comment (`full-mode.md:234`, `:266`). If the bot reads only its own threads, a finding the agent declines there stays open until the code changes.
4. **Does the bot re-review on push?** Babysit pushes fixes. Before it calls a PR ready, it waits for a reviewer that reviewed an earlier head to review the new one (the review-still-expected guard, `skills/ce-babysit-pr/SKILL.md:55`, detailed in `references/settle.md:29-37`). A bot that doesn't run on `synchronize` never answers. Babysit can't trigger it with a label either: adding labels is not among the mutations babysitting authorizes (`SKILL.md:29`). So every run ends only after that bounded wait (about 30 minutes at most), and its ready call has to say the reviewer never came back, for example "Cautiously looks ready" (`SKILL.md:59`, `references/settle.md:37`).
5. **Do the bot's rules reach local review?** `ce-code-review`, which runs inside `ce-work` and `lfg`, takes its repo-rule criteria only from `CODING_STANDARDS.md`, else `CLAUDE.md` / `AGENTS.md` (`skills/ce-code-review/references/scope.md:131-139`). Rules kept in a bot-only file, like `.claude/review/rules.md`, are invisible to it.

For each "yes" on 1-3 or "no" on 4-5, pick one: change the bot, turn babysit off (`auto_babysit: false`), or remove the bot. pururu removed the bot and kept babysit on.

## Why This Matters

The failure is silent. Nothing errors. The PR goes green, threads read as resolved with a reasoned reply from the owner's account, and the owner never sees the finding the agent declined. Branch rules don't catch it: pururu's `main` ruleset requires review threads to be resolved, and the agent resolves them. The bot's check was not a required status check either. The loop that should add a second opinion ends up removing one.

## When to Apply

- Before turning on `ce-babysit-pr` (or leaving `auto_babysit` at its default) in a repo with any automated reviewer.
- Before adding a review bot or review GitHub Action to a repo that already uses the CE flow.
- Before widening Greptile's review trigger rules on pururu. Greptile left the PR flow on 2026-09-30 because its trial credits ran out (`docs/superpowers/plans/2026-09-30-refactor-d2-running-program.md:58`), but it is still installed: `greptile-apps[bot]` commented on PR #73 that the PR "does not match any of the 1 configured review trigger rule", and a `greptile` label exists. Run the five checks against Greptile before it reviews PRs.
- Before reusing the PR-flow steps of the older plans in `docs/superpowers/plans/` (most of the refactor A-D plans): they add the `claude-review` label, which now triggers nothing, and some call `@greptileai review`, which would bring Greptile back without these checks.
- Not needed for the `@claude` assistant in `.github/workflows/claude.yml`: it answers when called and keeps no findings.

## Examples

The pururu bot, from the files PR #73 deletes (still on `origin/main` at the time of writing):

- Trigger, no re-review on push (check 4), `origin/main:.github/workflows/claude-code-review.yml:10-12`:

  ```yaml
  # A full review when opened; a re-review (incremental) when labeled claude-review.
  # Add synchronize to review every push.
  types: [opened, reopened, ready_for_review, labeled]
  ```

- Resolved means dismissed (check 1), `origin/main:.claude/review/review.md:52-53`:

  ```
  - **open**: an unresolved thread, or a summary-only finding;
  - **dismissed**: a resolved thread. Never post it again, whatever you find.
  ```

- Only the owner's replies count, and they can withdraw a finding (check 2), `origin/main:.claude/review/review.md:16-18` (reads only the bot's and `mguilarducci`'s comments), `:49` (the GraphQL query keeps `owner_replies` by `mguilarducci`), and `:135`:

  ```
  - **withdrawn**: it was wrong, or the owner's reply gives a reason the code bears out.
  ```

- A top-level reply can't withdraw a summary-only finding (check 3), `origin/main:.claude/review/review.md:44` and `:52`: they live in the summary's `summary_only` state. The bot reads only its own marked summary (`:37-41`) and the replies in its own review threads (`:49`), never other top-level comments.

What PR #73 did instead: it deleted the bot's four files, set `auto_babysit: true` in `.compound-engineering/config.yaml`, and dropped `rules.md` without moving it anywhere. The cost it accepts: a PR opened outside `ce-work` / `lfg` gets no automated review. The leftover `claude-review` label now triggers nothing.

## Related

- `docs/plans/2026-10-01-1406-chore-retire-review-bot-plan.md`: the plan for PR #73, with the decisions and the accepted consequence.
- `docs/superpowers/specs/2026-09-29-claude-review-design.md` and `docs/superpowers/plans/2026-09-29-claude-review.md`: the retired bot's design and plan, kept as history.
