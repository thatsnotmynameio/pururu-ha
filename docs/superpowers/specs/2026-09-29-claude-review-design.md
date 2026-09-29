# Claude review at Greptile's level — design

Builds on the Claude Code Review workflow as fixed in #34 (the code-review plugin's tools, background tasks off) and #35 (actions pinned by SHA; drafts, forks and bots skipped). Only the review's own files change: the Claude workflows and the review's prompts and scripts. The integration's code, tests and docs don't.

## Goal

A review of each pull request that reads like Greptile's on this repo:
- A summary comment, edited in place: a confidence score, a risk level and the findings.
- A few inline findings, each confirmed and with a concrete failure scenario.
- A re-review that looks only at the new commits and resolves the threads they fix.

The review is made by Claude on the owner's subscription, and it says the same thing every time about how it posts. Today's plugin reviews once, decides alone what and how to post, and has passed green without posting (anthropics/claude-code-action#1646, #1087).

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
| Who writes, who posts | **Claude reads and answers; code posts.** Claude gets `Read`, `Grep`, `Glob` and subagents, no shell, no write tool. It returns one JSON object through the action's `--json-schema` (`structured_output`). A script turns that into the summary, the inline review and the resolved threads. The format, the cap on findings and the score's caps are code, not a request to the model. Rejected: Claude posting through the action's tools, which is how the plugin fails silently today. |
| Identity | **`claude[bot]`**, as the `@claude` replies from `claude.yml`. The action revokes the Claude App token when its step ends, so `publish.py` gets its own the way the action does (`src/github/token.ts` at the pinned commit): a GitHub OIDC token with audience `claude-code-github-action`, POSTed as a bearer to `https://api.anthropic.com/api/github/github-app-token-exchange`, which answers `{token}` (or `{app_token}`). The token is revoked at the end (`DELETE /installation/token`). If the exchange fails, the review is posted with the job's `GITHUB_TOKEN`, as `github-actions[bot]`, and a warning says why. The exchange refuses a workflow that differs from main's. Accepted: the endpoint isn't documented. It is the one the pinned action uses, and the fallback keeps the review working if it changes. |
| Claude's token | The action gets `github_token: ${{ github.token }}`: no OIDC exchange for the Claude step, and so no "workflow validation" skip. A PR that changes this workflow is reviewed too, by its own copy. Claude can't use the token: it has no shell and no network. |
| Where the process lives | `.github/claude-review/` (scripts, schema) and `.claude/review/` (prompts), **taken from the base commit** by a sparse checkout, as the action already does with `.claude/`. A PR changes how it is reviewed only once merged. A base without them (the PR adding them, a stacked PR) ends with a job-summary note, not a failure. |
| Model | Opus, `--max-turns` bounded, subagents in the foreground (`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS: 1`, the #1646 workaround). |
| How it finds bugs | Parallel finders by lens, chosen by what changed: correctness; lifecycle (async, restore, reload, registries); configuration (schema, translations en + pt-BR, entity IDs); docs, tests and CI consistency. Then skeptical verifiers try to refute each candidate. Only CONFIRMED findings with a concrete scenario are returned. In an incremental review, one more finder sweeps the whole PR for P0/P1 only. |
| What it never flags | What CI enforces (ruff, ruff format, mypy strict, hassfest, the tests, docs.page links, Sonar), style, nits, and `docs/superpowers/`. Lockfiles (`uv.lock`, `pnpm-lock.yaml`) are left out of the diffs. |
| Severity | P0: breaks every user or loses data. P1: a real bug on a normal path. P2: a real but narrow bug, a contract or docs contradiction, at most one missing test per PR. Calibrated on Greptile's findings here. |
| Caps, in code | At most 6 new findings per round, highest severity first; the rest are counted in the summary. Confidence is the model's, capped by the open findings: any P0 → at most 1; two or more P1 → at most 3; any P1 → at most 4. |
| Anchoring | Each new finding is posted as its own review comment (`POST /pulls/{n}/comments`: no review body to fill, and its ID comes back at once) on RIGHT-side lines present in the PR's diff hunks (`line`, optional `start_line`). A finding outside the hunks, or one GitHub refuses, is listed in the summary with a link to the file line: the only fallback. A suggestion is kept only when it replaces exactly the anchored lines. |
| State | In the summary comment itself, in a hidden marker: the last reviewed SHA and each finding's ID with its comment ID. No artifact, no database. The summary is found by its marker `<!-- pururu-review:summary -->` among comments by `claude[bot]` or `github-actions[bot]`. |
| Incremental | When the marker's SHA is an ancestor of the head and no merge of the base came in since: review `last..head`, and judge each earlier finding as fixed, outstanding or withdrawn. Otherwise (a first review, a force-push, the base merged in): a full review, with the earlier findings still judged. A re-review with no new commit, or whose new commits only merge the base, runs no model. |
| Threads | The earlier threads the model judges fixed or withdrawn are resolved (GraphQL `resolveReviewThread`; `main` requires every thread resolved); a failure only warns. A thread the owner resolved drops its finding. Outstanding ones stay listed in the summary. Replies to findings go through `@claude` (`claude.yml`), unchanged. |
| Triggers | `opened`, `reopened`, `ready_for_review`: a full review. `labeled` with `claude-review`: a re-review (incremental when possible), drafts included; the label is removed afterwards. Every push (`synchronize`) is **not** on yet: the owner decides later, and it is one line in `on:`. |
| Skipped | Drafts (unless labeled), forks (no secret), PRs by bots (the action refuses bot actors). One review at a time per PR (`concurrency`, not cancelled). |
| Failure | If Claude fails or returns nothing, the summary says so, with the run's link, and the job fails. |

## Files

```
.github/workflows/claude-code-review.yml   one job: checkouts → context → Claude → publish
.github/claude-review/
  context.py      builds .pururu-review/ and the step outputs
  publish.py      token, summary, review, resolved threads, label, job summary; --dry-run
  schema.json     Claude's output contract, passed to --json-schema
.claude/review/
  review.md       the process: context, lenses, finders, verifiers, earlier findings, output
  rules.md        this repo's severity, never-flag list, pointers into CLAUDE.md, score and risk rubric
```

`claude.yml` is unchanged. The code-review plugin is no longer used.

### `context.py`

Standard library, `git` and `gh` (read-only `GH_TOKEN`). In the PR's checkout (full history), it writes `.pururu-review/`:
- `pr.diff`: merge base to head;
- `incremental.diff` in incremental mode;
- `context.md`: mode, SHAs, title and body, commits, files, and the earlier findings still open, with the replies in their threads;
- `state.json` for `publish.py`: the summary comment (ID, author, body), the last reviewed SHA and the earlier findings with their thread IDs.

Step outputs: `ready`, `skip`, `mode`, and `schema` (compact `schema.json`, for `--json-schema`).

### Claude's output (`schema.json`)

```
confidence   0-5
risk         low | medium | high | critical
verdict      one line
summary      a paragraph
files        [{path, note}]
diagram      optional mermaid
findings     [{severity P0|P1|P2, title, path, line, start_line?, scenario, suggestion?, fix_prompt}]   IDs are given by publish.py
earlier      [{id, status fixed|outstanding|withdrawn, note}]
```

Flat, no `$ref`.

### `publish.py`

Standard library (`urllib`). It:
1. gets the token;
2. applies the caps;
3. posts the new findings as one review (event `COMMENT`);
4. upserts the summary. If the old one can't be edited, because the other identity wrote it, it posts a new one and leaves the old;
5. resolves the fixed threads;
6. removes the `claude-review` label;
7. writes the job summary;
8. revokes the token.

`--dry-run` prints the payloads and calls nothing.

### Summary format

```
<h3>Confidence Score: 4/5</h3>

**Medium risk** — one-line verdict

<h3>Findings</h3>
1. <kbd>P1</kbd> **Title** [→](thread link)
2. <kbd>P2</kbd> **Title** (path:line, outside the diff)

<details><summary>Important files changed</summary> table </details>
optional mermaid diagram
<sub>Last reviewed commit: abc1234 · Reviewed by Claude</sub>
<!-- pururu-review:summary -->
<!-- pururu-review:state {"sha": "...", "findings": {"id": comment_id}} -->
```

Inline comment:

````
<kbd>P1</kbd> **Title**

Failure scenario.

```suggestion
replacement lines
```

<details><summary>Prompt to fix with AI</summary> ... </details>
````

## Testing

Nothing here runs in the repo's test suite: the scripts aren't the integration.
- **Locally:**
  - `actionlint` on the workflow and `py_compile` on the scripts;
  - `context.py` on real merged PRs (#30, #33) in a clone: full mode, incremental mode (a fake earlier marker on an intermediate commit) and a base merge (back to full);
  - `publish.py --dry-run` on sample outputs, checking:
    - a clean PR;
    - more than 6 findings, one outside the hunks;
    - a re-review with fixed and outstanding findings.
- **On GitHub, after merge:** a probe PR with a planted bug, as #36.
  - The review runs, posts as `claude[bot]` and finds the bug.
  - A fix commit plus the `claude-review` label gives an incremental review that resolves the thread.

## Out of scope

- Answering replies in threads, since `@claude` already does.
- Learning from reactions.
- Defenses against third parties: only the owner opens PRs here, and forks and bots are skipped.
- Reviewing every push, which is left to the owner's decision.
