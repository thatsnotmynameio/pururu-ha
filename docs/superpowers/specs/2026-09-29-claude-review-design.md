# Claude review at Greptile's level — design

Builds on the Claude Code Review workflow as fixed in #34 (the tools the review needs, background tasks off) and #35 (actions pinned by SHA; drafts, forks and bots skipped). Only the review's own files change: its workflow and its prompts. The integration's code, tests and docs don't.

## Goal

A review of each pull request that reads like Greptile's on this repo:
- A summary comment, edited in place: a confidence score, a risk level and the findings.
- A few inline findings, each confirmed and with a concrete failure scenario.
- A re-review that looks only at the new commits and resolves the threads they fix.

All of it by Claude, on the owner's subscription, posted as `github-actions[bot]`.

## What Greptile does here

Greptile's reviews on this repo (PRs up to #33):
- **Summary:** one comment, edited at each round:
  - `Confidence Score: N/5`, a risk level and a one-line verdict;
  - the findings, each linking to its thread;
  - a collapsed table of the important files and an optional diagram;
  - `Last reviewed commit`.
- **Findings:** 0 to 6 per PR (33 P1, 26 P2 in all, no nits). Each inline comment has:
  - a `P1`/`P2` badge and a bold title;
  - the scenario;
  - a committable suggestion when one fits;
  - a collapsed "Prompt to fix with AI".
- **Re-reviews:** after new commits, Greptile reviews what changed and leaves earlier threads alone unless the code fixed them.

## Decisions

| Question | Decision |
|---|---|
| Who posts | **Claude posts the inline findings; the workflow posts the rest.** Inline findings go through the action's own tool (`mcp__github_inline_comment__create_inline_comment`, `confirmed: true`). Claude writes the summary and the thread IDs to resolve to `/tmp/pururu-review/` (`summary.md`, `resolve.txt`). A second job, `claude-review-publish`, gets them as an artifact and posts them with `gh`. It runs no model and checks nothing out, and it holds `contents: write` only because GitHub requires it for `resolveReviewThread` (`pull-requests: write` is refused with "Resource not accessible by integration", seen on #42). The Claude job keeps `contents: read`, `pull-requests: write` for the inline findings, and `issues: read`. That step finds this review's summary by its marker, edits it or posts one, and resolves only the listed threads that this review opened. Everything uses the jobs' `GITHUB_TOKEN` (`github_token: github.token` for Claude), so all of it is `github-actions[bot]`. Until 2026-09-30 the review posted as `claude[bot]` with the Claude App token, which can write contents (push, tags, releases). In a public repo a prompt injection must not reach that. A summary left by `claude[bot]` can't be edited, so a new one is posted. No script of our own. Rejected: a publishing script that enforces the format in code. It works, but it is a few hundred lines of Python and tests for a repository with one author. If Claude's format drifts, that is the fallback. |
| Where the process lives | `.claude/review/review.md` (how to review and post) and `.claude/review/rules.md` (this repo's rules). The action restores `.claude/` from the base branch before Claude starts, so a PR can't change its own review. The workflow's prompt only points at `review.md`. |
| Model | Opus, `--max-turns` bounded, subagents in the foreground (`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS: 1`, the anthropics/claude-code-action#1646 workaround). |
| Tools | `Read`, `Grep`, `Glob`, subagents, the inline-comment tool, read-only `git` (`diff`, `log`, `show`, `merge-base`, `rev-parse`, `rev-list`), and read-only `gh`: `gh pr view`, `gh pr diff`, and `gh api` queries. `gh` reads local files by itself (`-F x=@<path>`, `--input`, `--body-file`), which a `Read` deny doesn't cover, and it can write. So these are denied, wildcard rules replayed locally: `Bash(gh *@*)`, `Bash(gh *--input*)`, `Bash(gh *--body-file*)`, `Bash(gh * -X *)`, `Bash(gh *--method*)`, `Bash(gh *mutation*)`, `Bash(gh *--comments*)` and `Bash(gh pr comment:*)`. `Write` is allowed only inside `/tmp/pururu-review/`, through the rule `Edit(//tmp/pururu-review/**)`: file writes are governed by `Edit` rules, and `Edit` must not be disallowed. No other edit or write. Found by the review of its own hardening PR (#41). |
| Public repository | Anyone can comment on a pull request here, so a comment is untrusted text that could try a prompt injection. Three guards:<br>1. **No outsider text reaches Claude.** The comments and threads queries filter with `--jq` to this review's own comments (and `claude[bot]`'s from before 2026-09-30) and the owner's (`mguilarducci`) replies. `--comments` is denied, and the `review-reader` subagents never use `gh`.<br>2. **The process environment can't be read.** That is where the OAuth token lives. `Read`/`Grep`/`Glob` on `//proc/**` and `//sys/**` are denied, and so are `git diff --no-index` with any flags and `gh` reading a file (see Tools). This was replayed locally.<br>3. **The token can't push, tag or release** (see Who posts).<br>Forks and bots are skipped, and only writers can open a same-repo PR or add the label. |
| How it finds bugs | Parallel finders by lens, chosen by what changed: correctness; lifecycle (async, restore, reload, registries); configuration (schema, translations en + pt-BR, entity IDs); docs, tests and CI consistency. Then skeptical verifiers try to refute each candidate. Only CONFIRMED findings with a concrete scenario are posted. In an incremental review, one more finder sweeps the whole PR for P0/P1 only. |
| What it never flags | What CI enforces (ruff, ruff format, mypy strict, hassfest, the tests, docs.page links, Sonar), style, nits, `docs/superpowers/`, lockfiles. |
| Severity | P0: breaks every user or loses data. P1: a real bug on a normal path. P2: a real but narrow bug, a contract or docs contradiction, at most one missing test per PR. |
| Caps | At most 6 new findings per round, most severe first. Confidence capped by the open findings: any P0 → at most 1; two or more P1 → at most 3; any P1 → at most 4. The review follows them. They're in `review.md`, not in code. |
| State | The earlier findings are Claude's review threads themselves: unresolved ones are open, resolved ones are dismissed and never posted again. This includes a thread left by a run that died before its summary. The summary comment keeps the rest in a hidden line, `<!-- pururu-review:state {"sha": "...", "summary_only": [...]} -->`: the last reviewed commit, and the findings listed only in the summary. The summary is found by its marker `<!-- pururu-review:summary -->` among this review's comments (`github-actions[bot]`, earlier `claude[bot]`), and edited by ID. |
| Checkout | The PR's head commit (`ref: head.sha`), not GitHub's test-merge commit, with full history. The head sha is in the prompt; it goes into the state, the links and each comment's `commit_id`. |
| Subagents | Finders and verifiers are a `review-reader` agent (`.claude/agents/review-reader.md`: `Read`, `Grep`, `Glob`, `Bash`), so they can't post. The action posts an unconfirmed inline call without classifying it when it runs on an OAuth token. |
| Instructions vs. the PR's `CLAUDE.md` | The action restores `CLAUDE.md` and `.claude/` from the base branch: those are the instructions. The PR's own `CLAUDE.md` is reviewed as a change (`git show <head>:CLAUDE.md`). |
| Incremental | When the state's commit is an ancestor of the head and no merge came in since, the review looks at `git diff <state sha>..HEAD`. It judges each earlier finding as fixed, outstanding or withdrawn. Otherwise it does a full review. A re-review with nothing new changes nothing and says so in the summary. |
| Threads | Earlier findings judged fixed or withdrawn have their threads resolved by the `claude-review-publish` job (GraphQL `resolveReviewThread`, only threads this review opened; `main` requires every thread resolved). A thread the owner resolved drops its finding. Replies to findings stay with `@claude` (`claude.yml`), unchanged. |
| Triggers | `opened`, `reopened`, `ready_for_review`: a full review. `labeled` with `claude-review`: a re-review, drafts included; a last step removes the label. Every push (`synchronize`) is **not** on yet: the owner decides later, and it is one line in `on:`. |
| Skipped | Drafts (unless labeled), forks (no secret), PRs by bots (the action refuses bot actors). One review at a time per PR (`concurrency`, not cancelled). |
| A PR changing the workflow | Not reviewed. The action refuses to run a workflow that differs from main's, which is how #34 and #35 went. Accepted. |

## Files

```
.github/workflows/claude-code-review.yml   one job: checkout (full history) → Claude → remove the label
.claude/review/review.md                   the process: context, lenses, finders, verifiers, earlier findings, posting
.claude/review/rules.md                    this repo's severity, never-flag list, pointers into CLAUDE.md, score and risk
.claude/agents/review-reader.md            the read-only subagent for finders and verifiers
```

`claude.yml` is unchanged. The code-review plugin is no longer used.

## Formats

The summary:

```
<h3>Confidence Score: 4/5</h3>

**Medium risk** — one-line verdict

One short paragraph on the change.

<h3>Findings</h3>
1. <kbd>P1</kbd> **Title** [→](thread URL)
2. <kbd>P2</kbd> **Title** [→](thread URL) (still open)

<details><summary>Important files changed</summary> table </details>
optional mermaid diagram
<sub>Last reviewed commit: abc1234 · Reviewed by Claude</sub>
<!-- pururu-review:summary -->
<!-- pururu-review:state {...} -->
```

An inline finding:

````
<kbd>P1</kbd> **Title**

Failure scenario.

```suggestion
replacement lines
```

<details><summary>Prompt to fix with AI</summary> ... </details>
````

## Testing

There is no unit test; the review's files are prompts and a workflow.
- **Locally:** `actionlint` on the workflow.
- **On GitHub, after merge:** a probe PR with a planted bug, as #36.
  - The review posts, as `github-actions[bot]`, a finding on the bug and the summary.
  - A fix commit plus the `claude-review` label gives an incremental review that resolves the thread, edits the summary and removes the label.

## Out of scope

- Answering replies in threads, since `@claude` already does.
- Learning from reactions.
- Defenses against third parties.
- Reviewing every push, which is left to the owner's decision.
