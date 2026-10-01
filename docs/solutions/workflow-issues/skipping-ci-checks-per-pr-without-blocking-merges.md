---
title: "Skip CI checks only by job-level conditions in one caller workflow, behind one required check; Sonar's app check and CodeQL's code scanning rule can't be skipped"
date: 2026-10-01
category: workflow-issues
module: CI workflows (.github/workflows)
problem_type: workflow_issue
component: development_workflow
severity: medium
applies_when:
  - Making a CI check run only when a pull request changes what it checks, with required status checks in a ruleset
  - Tempted to add paths, paths-ignore, branch or commit-message filters to a workflow whose check is required
  - Splitting a workflow into reusable workflows (uses) with a concurrency group
  - Wanting to skip CodeQL or SonarCloud on pull requests that touch nothing they scan
retire_when: "GitHub stops leaving a required check Pending when its workflow is skipped by a filter, or lets the code_scanning ruleset rule pass without an uploaded CodeQL analysis, or Sonar's app posts its check without a CI scan; check GitHub's troubleshooting-required-status-checks docs and the repository ruleset 'pururu checks'"
tags: [ci, github-actions, required-status-checks, rulesets, reusable-workflows, codeql, sonarcloud, concurrency]
---

# Skip CI checks only by job-level conditions in one caller workflow, behind one required check; Sonar's app check and CodeQL's code scanning rule can't be skipped

## Context

Issue #74 made pururu-ha's CI run each check only when a pull request changes something that check covers. The change is on the issue #74 branch; its merge, and the ruleset edit that goes with it, are pending.

Before the change, ruleset 24076959 "pururu checks" required three status checks: "Tests and SonarQube" and "HACS validation" (GitHub Actions), and "SonarCloud Code Analysis" (the SonarCloud app, integration 12526). It also had a `code_scanning` rule for CodeQL (alerts `errors`, security `high_or_higher`). CodeQL runs on GitHub's default setup for `actions` and `python`. The ruleset and the default setup live in GitHub's settings, not in the repo (plan `docs/plans/2026-10-01-1504-chore-ci-runs-what-changed-plan.md:131`).

The obvious fix, `paths`/`paths-ignore` filters on each workflow, blocks merges. Two of the required gates can't be skipped from this repo at all. None of that shows in the final YAML: the repo has no CodeQL workflow and no ruleset file. A future engineer who sees "CodeQL runs on every PR even for a docs typo" or "why no `concurrency:` in build.yml?" will likely try the broken approaches again. This doc records why.

## Guidance

### 1. Skip by job `if:`, never by workflow path filters

GitHub treats the two kinds of skip differently:

- A required check from a workflow skipped by a path, branch or commit-message filter stays "Pending", and the merge is blocked.
- A job skipped by its own `if:` reports "Success".

Source: GitHub docs, "Troubleshooting required status checks" (https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/troubleshooting-required-status-checks). The repo states the same rule in the `ci.yml` header (`.github/workflows/ci.yml:7-10`).

So the layout is one caller workflow, `.github/workflows/ci.yml`, triggered on `pull_request` (and `workflow_dispatch`) (`ci.yml:14-17`):

- Job `changes` checks out the PR's merge commit with `fetch-depth: 2` and diffs it against its first parent (`ci.yml:38-46`). It pipes the file list into `changes.py pull_request` and exports `build`, `docs` and `hacs` as job outputs (`ci.yml:33-36`, `:51`).
- Jobs `build`, `docs` and `validate` call `build.yml`, `docs.yml` and `validate.yml` through `uses:`, each guarded by `if: needs.changes.outputs.<check> == 'true'` (`ci.yml:58-72`).
- Job "CI ok" has `needs:` on all four jobs and `if: always()`. It fails only when a needed job's result is `failure` or `cancelled`, so skipped jobs pass (`ci.yml:74-83`).

```yaml
ok:
  name: CI ok
  needs: [changes, build, docs, validate]
  if: always()
  steps:
    - if: contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled')
      run: exit 1
```

"CI ok" is meant to be the only required Actions check (`ci.yml:9-10`, `CLAUDE.md:107`). Because there is one required check, splitting or adding a check never needs a ruleset change. The checks must be reusable workflows called from one file because `needs:` only reaches jobs in the same workflow file; separate workflows can't feed one aggregate job.

`changes.py` runs everything unless a rule allows a skip:

- An empty diff runs every check (`changes.py:74-75`).
- A file in no group runs every check (`changes.py:79`).
- Any event other than `pull_request` runs every check (`changes.py:97-98`).
- A change to `.github/workflows/` runs every check (`changes.py:42`, `:48-52`).

`changes.py` never classifies its own change. When `changes.py` is in the diff, `ci.yml` sets all three outputs to true without running it (`ci.yml:47-50`). Otherwise a broken fallback could skip the very tests that would catch it.

### 2. Called workflows: no `pull_request` trigger, no workflow-level `concurrency`

- Inside a called workflow, `github.workflow` is the caller's name. A called workflow with `concurrency: group: ${{ github.workflow }}-${{ github.ref }}` therefore lands in the caller's group, and GitHub cancels the run at startup with "deadlock was detected for concurrency group" (plan KTD2, `docs/plans/2026-10-01-1504-chore-ci-runs-what-changed-plan.md:143`). Only the caller declares concurrency (`ci.yml:22-26`). `build.yml`, `docs.yml` and `validate.yml` have none.
- A called workflow that keeps its own `pull_request` trigger runs each check twice per PR. `build.yml` and `docs.yml` trigger only on `workflow_call` and `workflow_dispatch` (`build.yml:12-14`, `docs.yml:11-13`). `validate.yml` adds only its weekly cron (`validate.yml:7-11`).
- `release.yml` keeps its own `concurrency: group: release` (`release.yml:15-17`). That name is not derived from `github.workflow`, so it doesn't collide when Release calls Build and Validate on every push to `main` (`release.yml:20-25`).

### 3. "SonarCloud Code Analysis" leaves the required list; our Sonar job enforces the gate

The project uses CI-based analysis (automatic analysis is off). "SonarCloud Code Analysis" is posted by the Sonar app only when a CI scan runs. Our jobs can't post it, and the ruleset pins it to the app. Sonar staff confirm that with CI analysis and that check required, the scan must run on every PR (https://community.sonarsource.com/t/github-pull-request-scan-sonarcloud-code-analysis-expected-waiting-for-status-to-be-reported/106497). A docs-only PR that skips Build would therefore stay blocked.

Resolution:

- The app check leaves the ruleset's required checks (plan R10, `:80`).
- Build's `SonarQube` job waits for the quality gate on pull requests only, so a red gate fails our job, which "CI ok" then reports (`build.yml:102-110`):

```yaml
with:
  args: ${{ github.event_name == 'pull_request' && '-Dsonar.qualitygate.wait=true' || '' }}
```

The flag is kept out of `sonar-project.properties` on purpose: it holds only project keys, paths and suppressions (`sonar-project.properties:1-9`). A gate wait there would also apply on `main`, where Release calls Build, and a red gate would stop a release (`build.yml:103-104`, `docs/develop/releases.mdx:77`).

### 4. CodeQL can't be skipped per PR while the ruleset's `code_scanning` rule exists

The code scanning rule doesn't wait for a check name. It waits for an uploaded CodeQL analysis, for every language `main` has. GitHub blocks the merge while an analysis is in progress or the tool isn't configured (https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets). A job-level `if:` skip or a `paths-ignore` uploads nothing, so the PR stays BLOCKED indefinitely. Reports:

- gerwaric/acquisition#207, a deliberate experiment: "the if:-skip satisfies both required status checks (rollup=SUCCESS) but the PR stays BLOCKED because the code_scanning ruleset rule never receives a CodeQL analysis".
- nics-dp/meta#313.
- davetashner/supply-checkout#158: the rule wants results for every language `main` has.

Also, while default setup is on, GitHub rejects uploads from an advanced CodeQL workflow (https://docs.github.com/en/code-security/code-scanning/troubleshooting-sarif-uploads/default-setup-enabled). A repo workflow can't take over CodeQL without first turning default setup off.

The owner kept the rule and left CodeQL on default setup for every PR, so nothing in the repo runs CodeQL (`ci.yml:11`, `docs/develop/releases.mdx:61`, `:86`; plan `:46`, `:88`). The cost: every PR waits for CodeQL before it can merge, an estimated 1 to 1.5 minutes (plan estimate from step timings, not yet measured), even when every other check is skipped.

The alternative was to gate CodeQL in our own job and drop the code scanning rule. It was considered and rejected (plan `:46`).

### 5. Tests that read non-code files belong to that file group's check

Some test modules read `docs/` pages. If they stayed in Build, a docs-only PR (which skips Build) could break `pytest` without anything noticing. They now live in `tests/docs/`:

- `tests/conftest.py` marks them `docs` (`tests/conftest.py:18`, `:49-50`).
- The default run deselects them with `-m "not docs"` (`pyproject.toml:34-36`).
- The Docs workflow runs them (`docs.yml:33-53`).
- An AST guard fails any test outside `tests/docs/` that names `docs/` (`tests/test_code.py:219-255`; `conftest.py` and `test_changes.py` are allowlisted, and `test_code.py` skips itself).

A code review then found that Release, which calls Build rather than Docs, had lost those tests on `main`. Build's lint job now runs them outside pull requests (`build.yml:44-47`):

```yaml
- if: github.event_name != 'pull_request'
  run: uv run --locked pytest -m docs tests/docs -n 0
```

### 6. The ruleset swap is manual and comes after "CI ok" has run once

The PR that introduces "CI ok" no longer produces "Tests and SonarQube". It stays blocked until the owner edits ruleset 24076959: the three required checks ("Tests and SonarQube", "HACS validation", "SonarCloud Code Analysis") are replaced with "CI ok" (source GitHub Actions), and the code scanning rule stays. This happens after "CI ok" has run on the PR, so GitHub knows the check name (plan KTD12, `:153`). As of this writing the PR and the swap are pending.

## Why This Matters

- Path filters look like the natural fix, and they fail silently: the PR shows a pending check that never arrives.
- The two gates that can't be skipped (Sonar's app check and the CodeQL code scanning rule) aren't declared anywhere in the repo. Nothing in the code warns the next person who tries to skip them.
- The concurrency deadlock only shows up once workflows are called. A `concurrency:` block that looks harmless, copied into a called workflow, cancels the whole CI run.
- Every "skip" also moves tests between workflows. Release runs a different set of workflows than CI, so moving a test can drop it from `main` unless both paths are checked.

## When to Apply

- Adding a new check to pururu-ha's CI, or a new file group to `changes.py`.
- Being tempted to add `paths`, `paths-ignore` or `branches` filters to any workflow whose check is, or feeds, a required check.
- Adding `concurrency:` to `build.yml`, `docs.yml` or `validate.yml`, or a `pull_request` trigger to any of them.
- Wanting faster docs-only or agent-file PRs by skipping CodeQL or Sonar.
- Editing ruleset 24076959, or moving CodeQL from default setup to an advanced workflow.
- Moving tests between workflows: check both the PR path (`ci.yml`) and the `main` path (`release.yml`).

## Examples

| PR changes | `changes.py` output | What runs | Merge gate |
|---|---|---|---|
| `docs/features/door.mdx` | `build=false docs=true hacs=false` | Docs (docs.page check and docs tests) | "CI ok" passes; CodeQL default setup still analyses the PR |
| `CLAUDE.md` only | all `false` | nothing but `changes` and "CI ok" | "CI ok" passes; CodeQL still about 1 to 1.5 min |
| `custom_components/pururu/manifest.json` | all `true` (code and hacs) | Build, Docs, Validate | all must pass |
| `.github/workflows/build.yml` | all `true` | everything | all must pass |
| `changes.py` | forced all `true` by `ci.yml:48-49`, `changes.py` not run | everything | all must pass |

To preview the checks locally: `git diff --name-only origin/main... | python3 changes.py pull_request` (`CLAUDE.md:21`, `docs/develop/releases.mdx:57-59`).

Anti-patterns that were rejected:

```yaml
# Blocks the merge: a required check from a filtered-out workflow stays "Pending"
on:
  pull_request:
    paths-ignore: ["docs/**"]
```

```yaml
# In a called workflow: github.workflow is the caller's name, so this deadlocks with ci.yml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
```

```yaml
# Leaves the PR BLOCKED: the code_scanning rule never receives an analysis
jobs:
  analyze:
    if: needs.changes.outputs.build == 'true'
    steps:
      - uses: github/codeql-action/analyze@...
```
