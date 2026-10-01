---
title: Retire the CI review bot, rely on the Compound Engineering flow - Plan
type: chore
date: 2026-10-01
execution: code
---

# Retire the CI review bot, rely on the Compound Engineering flow - Plan

## Summary

The Claude review bot leaves the repository. Review happens in the Compound Engineering flow: `ce-code-review` runs inside `ce-work` or `lfg` before a pull request is opened. The CE config records two explicit choices, babysit on and Fable for plan authoring. `CLAUDE.md` declares GitHub Issues as the tracker, where `ce-plan`'s Create Issue and the residual-findings filing look for it. Not a release: `manifest.json` is unchanged.

Why the bot goes: `ce-babysit-pr` and `ce-resolve-pr-feedback` clashed with it. The bot reviewed only on `opened`, `reopened`, `ready_for_review` and the `claude-review` label, so after a babysit push no new review came. It treated a resolved thread as dismissed for good, and it accepted a reply from the owner's login as the reason to withdraw a finding, which is the login `ce-resolve-pr-feedback` posts with.

## Implementation units

### U1. Remove the review bot

- Delete `.github/workflows/claude-code-review.yml`, `.claude/review/review.md`, `.claude/review/rules.md` and `.claude/agents/review-reader.md`.
- `.github/workflows/claude.yml` (the `@claude` assistant) stays, and so does the `CLAUDE_CODE_OAUTH_TOKEN` secret it uses.
- **Verification:** `git grep -n "claude-code-review\|review-reader\|\.claude/review"` matches only the history under `docs/superpowers/`. `uv run pytest` passes. On the pull request the "Claude review" job no longer appears, and the ruleset's required checks (Tests and SonarQube, HACS validation, SonarCloud Code Analysis) are unchanged; the bot's check was never one of them.

### U2. CE config

- In `.compound-engineering/config.yaml`, activate `plan_model: fable` in the "Model elevation" section and `auto_babysit: true` in the "ce-commit-push-pr babysit handoff" section. Keep the template's comments; every other key stays commented.
- `config.example.yaml` is unchanged: `ce-setup` compares it with the plugin's template.
- **Verification:** `ce-setup`'s `check-health` still reports "Project config healthy" and "Example config is current"; `grep -v '^\s*#' .compound-engineering/config.yaml` shows only those two keys.

### U3. Tracker in `CLAUDE.md`

- Add a bullet under "Releases and CI", in the section's style, declaring GitHub Issues with the literal `project_tracker: github`.
- **Verification:** the line is present; `uv run pytest` passes.

## Decisions

- Discard `rules.md`'s content, including "State left by the previous version" (session-settled: user-directed — chosen over moving it to `CLAUDE.md`, a Compound Pack or a `docs/solutions/` learning).
- Delete the bot's files rather than only disabling the workflow (session-settled: user-approved — git history keeps them).
- Babysit always on (session-settled: user-directed — chosen over `auto_babysit: false`: the automatic PR watch is wanted now that the conflicting bot goes).
- `plan_model: fable` in config (session-settled: user-directed — chosen over trying it per run first).

## Consequence accepted

Without the bot, a pull request is reviewed only when it goes through `ce-work` or `lfg`. A pull request opened outside that flow gets no automated review.

## Out of scope

- The `claude-review` label on GitHub (removing it is a change outside the repository).
- The claude-review spec and plan under `docs/superpowers/`, kept as history.
- `cross_model_review_mode`, left commented until the Codex decision.
