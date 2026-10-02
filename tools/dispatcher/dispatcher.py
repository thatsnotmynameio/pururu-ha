# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The author's ready issues become pull requests, one lfg session each.

Usage:
    python3 tools/dispatcher/dispatcher.py run [--sessions N] [--every SECONDS]

Polls this repository's open issues opened by the user `gh` is logged in as and
labelled `ready`, oldest first, skipping any still blocked by an open issue. Each
one gets a new worktree from origin/main under .claude/worktrees/ and a headless
`claude -p` session running lfg; at most N run at once (default 2), and the poll
runs every SECONDS (default 300). Labels show where an issue stands: `in progress`,
then `in review` (a pull request is open) and `ready to merge` (its required checks
pass), or `needs attention` (the session ended without one), or `paused` (the Claude
usage limit stopped it). Each issue also gets one status comment, edited in place: why
it waits in the queue, then a checklist of lfg's stages read from the session's log, its
last sentence and running time, then how it ended. A pause holds every start until a
minute past the limit's reset, or, with no reset known, until the next poll tries one
session. Past the hold, paused issues resume first, oldest first: the same conversation,
in the same worktree.
Every line it prints carries the time; each poll reports what it found. Logs, a record
of each session and the lock are in tools/dispatcher/.state/. Ctrl-C, SIGTERM or an error
judges the sessions that ended, as a poll would, and leaves the others running: their
issues stay `in progress`, and the next start follows them; paused issues stay paused, and
the next start resumes them from GitHub alone.
"""

import argparse
from collections.abc import Callable, Iterable, Mapping
import contextlib
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[2]  # the checkout: tools/dispatcher/ is two below it
READY = "ready"
IN_PROGRESS = "in progress"
IN_REVIEW = "in review"
READY_TO_MERGE = "ready to merge"
NEEDS_ATTENTION = "needs attention"
PAUSED = "paused"
MARGIN = 60  # seconds past a limit's reset before a session starts again
MARKER = "dispatcher-pause"  # the hidden marker's tag on a pause comment's last line
LIMIT = "limit"  # what paused a session: the usage limit, the session found gone at start,
INTERRUPTED = "interrupted"  # or `dispatcher.py stop`
STOPPED = "stopped"
CAUSES = {LIMIT: "the Claude usage limit stopped the session",
          INTERRUPTED: "the session was interrupted (found gone when the dispatcher started)",
          STOPPED: "the session was stopped with `dispatcher.py stop`"}
# lfg's stages in order, and the skills that enter each (compound-engineering 3.30.1), named
# without their plugin's prefix. A stage is marked done, current, pending, skipped, failed or
# paused.
STAGES = ("plan", "plan review", "implementation", "code review", "pull request", "CI")
SKILLS = {"ce-plan": "plan", "ce-brainstorm": "plan", "ce-doc-review": "plan review",
          "ce-work": "implementation", "ce-debug": "implementation",
          "ce-simplify-code": "code review", "ce-code-review": "code review",
          "ce-commit-push-pr": "pull request", "ce-babysit-pr": "CI"}
UNSTARTED = ("pending",) * len(STAGES)
LATEST = 200  # characters of the session's last sentence shown at most
STATUS = "dispatcher-status"  # the hidden marker's tag on the status comment's last line
QUEUED = "queued"  # the status comment's states beside the labels'
RUNNING = "running"
MARK_SIGNS = {"done": "✅", "current": "⏳", "pending": "⬜", "skipped": "➖", "failed": "❌",
              "paused": "⏸️"}


@dataclass(frozen=True)
class Issue:
    """An open issue as the queue sees it: its labels and how many open issues block it."""

    number: int
    labels: frozenset[str] = frozenset()
    blocked: int = 0
    title: str = ""


@dataclass(frozen=True)
class PullRequest:
    """An open pull request."""

    number: int
    url: str


@dataclass(frozen=True)
class Marker:
    """What resumes a paused session: its conversation, its branch, its reset (epoch seconds).

    `cause` is what paused it, one of `CAUSES`; only the usage limit has a reset.
    """

    session: str
    branch: str
    reset: int | None
    cause: str = LIMIT

    def fields(self) -> dict[str, Any]:
        """Its fields as JSON holds them, in a pause comment's marker or a session's record."""
        return {"session": self.session, "branch": self.branch, "reset": self.reset,
                "cause": self.cause}

    def line(self) -> str:
        """The hidden marker a pause comment ends with."""
        return f"<!-- {MARKER} {json.dumps(self.fields())} -->"


MARKER_LINE = re.compile(rf"<!-- {MARKER} (\{{.*\}}) -->")
SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def hidden(body: str, line: re.Pattern[str]) -> dict[str, Any] | None:
    """The JSON object a comment's last line holds when it is a hidden marker `line` matches."""
    lines = body.strip().splitlines()
    found = line.fullmatch(lines[-1].strip()) if lines else None
    try:
        record = json.loads(found[1]) if found else None
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def branch_of(branch: object, issue: int) -> bool:
    """Whether this is a branch the dispatcher names for the issue (`issue-N`, `issue-N-2`…)."""
    return isinstance(branch, str) and bool(re.fullmatch(rf"issue-{issue}(-\d+)?", branch))


def marker_from(fields: object, issue: int) -> Marker | None:
    """The marker these fields make, if its session, its branch and its cause are valid.

    The session must be a UUID, the branch this issue's and the cause one of `CAUSES`: the
    session becomes a `claude --resume` argument, and the branch a folder's name. A marker
    posted before causes existed has none: the usage limit was the only one.
    """
    if not isinstance(fields, dict):
        return None
    session, branch, reset = fields.get("session"), fields.get("branch"), fields.get("reset")
    cause = fields.get("cause", LIMIT)
    if (isinstance(session, str) and SESSION_ID.fullmatch(session) and branch_of(branch, issue)
            and (reset is None or (isinstance(reset, int) and not isinstance(reset, bool)))
            and isinstance(cause, str) and cause in CAUSES):
        return Marker(session, str(branch), reset, cause)
    return None


def marker_of(body: str, issue: int) -> Marker | None:
    """The valid marker on a comment's last line, if any (`marker_from`)."""
    return marker_from(hidden(body, MARKER_LINE), issue)


@dataclass(frozen=True)
class Hold:
    """No session starts until `until` (epoch seconds); a probe then starts one, not a slot's worth."""

    until: float | None = None
    probe: bool = False

    def holds(self, now: float) -> bool:
        """Whether starts wait at `now`."""
        return self.until is not None and now <= self.until

    def extend(self, reset: int | None, now: float) -> "Hold":
        """Fold in a limit ending: a known reset holds a margin past it, never shorter than before.

        An unknown reset holds this poll and probes at the next, unless a later hold is known; a
        known reset no later than a probe's hold keeps the probe, whatever order they come in.
        """
        if reset is not None:
            until = reset + MARGIN
            if self.probe and self.until is not None and until <= self.until:
                return self
            return Hold(max(self.until or 0.0, until))
        if self.until is not None and self.until > now:
            return self
        return Hold(now, probe=True)


@dataclass(frozen=True)
class Progress:
    """Where a session stands in lfg: a mark per stage of `STAGES`, and its last sentence."""

    marks: tuple[str, ...] = UNSTARTED
    latest: str | None = None


@dataclass(frozen=True)
class Ended:
    """A session whose process exited, with what GitHub says about its branch and issue."""

    issue: int
    worktree: str
    log: str
    reason: str
    prs: tuple[PullRequest, ...] = ()  # open pull requests from the session's branch
    linked: frozenset[int] = frozenset()  # the pull requests GitHub links to the issue
    limit: Marker | None = None  # the usage limit stopped it, as its log says
    resumed: Marker | None = None  # the marker it was resumed from
    progress: Progress = Progress()  # where it stood when it ended, as its log says


@dataclass(frozen=True)
class Review:
    """An issue `in review`, and whether an open pull request of it passes its required checks."""

    issue: int
    passing: bool


@dataclass(frozen=True)
class Snapshot:
    """What one poll read: ended sessions, issues in review, the ready and paused ones oldest first."""

    ended: tuple[Ended, ...] = ()
    reviews: tuple[Review, ...] = ()
    ready: tuple[Issue, ...] = ()
    paused: tuple[Issue, ...] = ()


@dataclass(frozen=True)
class Move:
    """Swap an issue's labels and comment when there is something to say, the comment first if so."""

    issue: int
    remove: tuple[str, ...]
    add: tuple[str, ...]
    comment: str | None = None
    comment_first: bool = False  # a pause: `paused` never exists without its marker


@dataclass(frozen=True)
class Link:
    """Add `Closes #issue` to a pull request's body, so merging it closes the issue."""

    pr: int
    issue: int


@dataclass(frozen=True)
class Dispatch:
    """Mark an issue in progress and start its session."""

    issue: int


@dataclass(frozen=True)
class Resume:
    """Mark a paused issue in progress and resume its conversation."""

    issue: int


type Action = Move | Link | Dispatch | Resume | Report


def local_time(epoch: float) -> str:
    """An epoch in this machine's local zone, with the zone's name."""
    return time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(epoch))


def inside(path: str | Path, root: Path) -> str:
    """A worktree or a log as a comment names it: its path under the checkout `root`.

    A comment is public and the machine's folders mean nothing to its reader; a path outside
    `root` is named by its last part.
    """
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return Path(path).name


def unrooted(text: str, root: Path) -> str:
    """Text a comment quotes (an error, a reason), with the checkout `root`'s prefix taken out."""
    return text.replace(f"{root}{os.sep}", "")


def needs_attention(issue: int, *paragraphs: str, remove: str = IN_PROGRESS) -> Move:
    """`remove` to needs attention, the comment saying why and how to queue it again."""
    return Move(issue, (remove,), (NEEDS_ATTENTION,),
                "\n\n".join(("Dispatcher: " + paragraphs[0], *paragraphs[1:],
                              "Add `ready` to queue it again.")))


def pause(session: Ended, marker: Marker, root: Path) -> Move:
    """In progress to paused, the comment first carrying the marker, unless it is the resumed one.

    The comment says the marker's cause; only the usage limit's speaks of a reset. Paths are
    named under the checkout `root`.
    """
    if marker == session.resumed:
        return Move(session.issue, (IN_PROGRESS,), (PAUSED,))
    if marker.cause != LIMIT:
        then = ("The session resumes at the first free slot."
                if marker.cause == INTERRUPTED else
                "The session resumes at the first free slot once the dispatcher runs again.")
    elif marker.reset is not None:
        then = f"It resets at {local_time(marker.reset)}; the session resumes then."
    else:
        then = "The reset time is unknown; the dispatcher tries again at the next poll."
    comment = "\n\n".join((f"Dispatcher: {CAUSES[marker.cause]}.", then,
                            f"Session: `{marker.session}`",
                            f"Worktree: `{inside(session.worktree, root)}`",
                            f"Log: `{inside(session.log, root)}`", marker.line()))
    return Move(session.issue, (IN_PROGRESS,), (PAUSED,), comment, comment_first=True)


def judge(session: Ended, root: Path) -> list[Action]:
    """A session ended: in review with an open pull request, paused at the limit, else attention.

    Each move is followed by its final report, from the marks the session's log left. Paths are
    named under the checkout `root`.
    """
    marks = session.progress.marks
    if not session.prs and session.limit:
        return [pause(session, session.limit, root),
                Report(session.issue, Status(PAUSED, marks_paused(marks),
                                             reset=session.limit.reset,
                                             cause=session.limit.cause))]
    if not session.prs:
        return [needs_attention(session.issue, "the session ended without a pull request.",
                                f"Reason: {unrooted(session.reason, root)}",
                                f"Worktree: `{inside(session.worktree, root)}`",
                                f"Log: `{inside(session.log, root)}`"),
                Report(session.issue, Status(NEEDS_ATTENTION, marks_stopped(marks)))]
    pr = session.prs[0]
    actions: list[Action] = [Move(session.issue, (IN_PROGRESS,), (IN_REVIEW,),
                                  f"Dispatcher: pull request {pr.url} is open."),
                             Report(session.issue, Status(IN_REVIEW, marks_opened(marks)))]
    if pr.number not in session.linked:
        actions.append(Link(pr.number, session.issue))
    return actions


def pick(ready: Iterable[Issue], running: set[int], free: int) -> list[int]:
    """The first `free` ready issues not blocked, not running, not in progress and not paused."""
    eligible = [issue.number for issue in ready
                if READY in issue.labels and not issue.labels & {IN_PROGRESS, PAUSED}
                and issue.number not in running and not issue.blocked]
    return eligible[:max(free, 0)]


def tick(snapshot: Snapshot, running: set[int], sessions: int, now: float = 0.0,
         hold: Hold = Hold()) -> list[Action]:
    """One poll's actions after the ended sessions' verdicts: reviews promoted, slots filled.

    `running` holds the issues whose sessions still run, the ended ones already out of it.
    The verdicts (`judge`) are applied apart, as a failed one is retried at the next poll.
    No session starts while `hold` holds; past it, paused issues resume before ready ones go,
    blockers notwithstanding, and a probe starts one session only. A promotion is reported ready
    to merge on the comment's marks; the other reviews in review as their comments stand (edit
    only), so a promoted issue's comment never goes back to CI current.
    """
    actions: list[Action] = []
    for review in snapshot.reviews:
        if review.passing:
            actions += [Move(review.issue, (IN_REVIEW,), (READY_TO_MERGE,)),
                        Report(review.issue, Status(READY_TO_MERGE), marks_passed)]
        else:
            actions.append(Report(review.issue, Status(IN_REVIEW), marks_kept))
    if hold.holds(now):
        return actions
    free = max(sessions - len(running), 0)
    cap = min(free, 1) if hold.probe else free
    resumed = [issue.number for issue in snapshot.paused if issue.number not in running][:cap]
    actions += [Resume(number) for number in resumed]
    actions += [Dispatch(number)
                for number in pick(snapshot.ready, running, cap - len(resumed))]
    return actions


def restore(markers: Iterable[Marker], now: float) -> Hold:
    """At start, the hold the paused issues' markers make: none once every known reset is past.

    Only the usage limit's markers hold: an interrupted or stopped session resumes at once.
    """
    hold = Hold()
    for marker in markers:
        if marker.cause == LIMIT:
            hold = hold.extend(marker.reset, now)
    return hold if hold.probe or hold.holds(now) else Hold()


def queue_lines(ready: Iterable[Issue], running: set[int], picked: list[int],
                slots: int, held: bool = False) -> list[str]:
    """What happens to each ready issue this poll: started, blocked, waiting or running."""
    in_use = len(running) + len(picked)
    lines = []
    for issue in ready:
        name = f'#{issue.number} "{issue.title}"' if issue.title else f"#{issue.number}"
        if issue.number in picked:
            fate = "dispatching"
        elif IN_PROGRESS in issue.labels or issue.number in running:
            fate = "already in progress"
        elif issue.blocked:
            plural = "s" if issue.blocked > 1 else ""
            fate = f"blocked by {issue.blocked} open issue{plural}, skipped"
        elif held:
            fate = "waiting for the Claude usage limit to reset"
        else:
            fate = f"waiting for a free session ({in_use} of {slots} in use)"
        lines.append(f"{name}: {fate}")
    return lines


def orphans(in_progress: Iterable[Issue], worktrees: Mapping[int, list[str]],
            root: Path) -> list[Move | Report]:
    """At start no session runs, so every issue in progress lost its session: it needs attention.

    Its comment's stage fails where the comment left it; its worktrees are named under `root`.
    """
    actions: list[Move | Report] = []
    for issue in in_progress:
        actions += [needs_attention(issue.number, "this issue was in progress with no session "
                                    "running (the dispatcher was stopped or crashed).",
                                    *(f"Worktree: `{inside(path, root)}`"
                                      for path in worktrees.get(issue.number, []))),
                    Report(issue.number, Status(NEEDS_ATTENTION), marks_stopped)]
    return actions


# The status comment

STATUS_LINE = re.compile(rf"<!-- {STATUS} (\{{.*\}}) -->")


@dataclass(frozen=True)
class Status:
    """What an issue's status comment says: its state, the checklist, and what the state shows.

    Queued shows its `reason` only; running, the checklist, the minutes since `started` and the
    `latest` sentence; paused, the checklist and its `cause`, with the limit's `reset` (None:
    unknown) for the usage limit alone; in review, ready to merge and needs attention, the
    checklist. Every one ends with the marks' marker.
    """

    state: str
    marks: tuple[str, ...] = UNSTARTED
    reason: str = ""
    latest: str | None = None
    started: float = 0.0
    reset: float | None = None
    cause: str = LIMIT

    def body(self, now: float) -> str:
        """The comment, in English, updated at `now`, its last line the marker holding the marks."""
        header = f"**Dispatcher status: {self.state}**"
        if self.state == RUNNING:
            stage = next((name for name, mark in zip(STAGES, self.marks, strict=True)
                          if mark == "current"), RUNNING)
            minutes = max(int((now - self.started) // 60), 0)
            header = f"**Dispatcher status: {stage}** (running {minutes} min)"
        parts = [header]
        if self.state == QUEUED:
            parts.append(self.reason[:1].upper() + self.reason[1:] + ".")
        else:
            parts.append("\n".join(f"{MARK_SIGNS[mark]} {name[:1].upper()}{name[1:]}"
                                   for mark, name in zip(self.marks, STAGES, strict=True)))
        if self.state == RUNNING and self.latest:
            longest = max((len(run) for run in re.findall("`+", self.latest)), default=0)
            fence = "`" * max(3, longest + 1)
            parts.append(f"Latest:\n{fence}text\n{self.latest}\n{fence}")
        if self.state == PAUSED:
            said = CAUSES[self.cause]
            text = said[:1].upper() + said[1:] + "."
            if self.cause == LIMIT:
                text += (f" It resets at {local_time(self.reset)}." if self.reset is not None
                         else " Its reset time is unknown.")
            parts.append(text)
        stamp = f"<!-- {STATUS} {json.dumps({'stages': list(self.marks)})} -->"
        parts.append(f"Updated {local_time(now)}\n{stamp}")
        return "\n\n".join(parts)


def waiting(blocked: int = 0, held: bool = False, until: float | None = None) -> str:
    """Why a queued issue waits: its open blockers, else the usage limit until then, else a slot."""
    if blocked:
        return f"blocked by {blocked} open issue{'s' if blocked > 1 else ''}"
    if held:
        return ("waiting for the Claude usage limit to reset at "
                + (local_time(until) if until is not None else "an unknown time"))
    return "waiting for a free session"


def status_marks(body: str) -> tuple[str, ...] | None:
    """The marks in a status comment's marker, if its last line is one holding a mark per stage."""
    record = hidden(body, STATUS_LINE)
    stages = record.get("stages") if record is not None else None
    if (isinstance(stages, list) and len(stages) == len(STAGES)
            and all(isinstance(mark, str) and mark in MARK_SIGNS for mark in stages)):
        return tuple(stages)
    return None


def same_status(old: str, new: str) -> bool:
    """Whether two bodies say the same, their `Updated` lines (just above the marker) aside."""
    def unstamped(body: str) -> list[str]:
        lines = body.strip().splitlines()
        if len(lines) > 1 and lines[-2].startswith("Updated "):
            del lines[-2]
        return lines
    return unstamped(old) == unstamped(new)


def marks_opened(marks: tuple[str, ...]) -> tuple[str, ...]:
    """A pull request opened: the stages before it done if entered, else skipped; CI current."""
    pr = STAGES.index("pull request")
    return tuple(("done" if mark in ("done", "current", "paused", "failed") else "skipped")
                 for mark in marks[:pr]) + ("done", "current")


def marks_passed(marks: tuple[str, ...]) -> tuple[str, ...]:
    """The pull request's required checks pass: CI done."""
    return (*marks[:-1], "done")


def marks_stopped(marks: tuple[str, ...]) -> tuple[str, ...]:
    """The session stopped: the current stage failed, else the paused one, else the plan."""
    stage = next((index for wanted in ("current", "paused") for index, mark in enumerate(marks)
                  if mark == wanted), 0)
    return tuple("failed" if index == stage else mark for index, mark in enumerate(marks))


def marks_paused(marks: tuple[str, ...]) -> tuple[str, ...]:
    """The usage limit stopped the session: the current stage paused."""
    return tuple("paused" if mark == "current" else mark for mark in marks)


def marks_kept(marks: tuple[str, ...]) -> tuple[str, ...]:
    """Nothing new: the marks as they are."""
    return marks


def marks_resumed(marks: tuple[str, ...]) -> tuple[str, ...]:
    """The session resumed: the paused stage current again."""
    return tuple("current" if mark == "paused" else mark for mark in marks)


type Change = Callable[[tuple[str, ...]], tuple[str, ...]]


@dataclass(frozen=True)
class Report:
    """Show `status` on the issue's status comment, posting the comment only if `create`.

    With `change`, the marks are `change` of the ones the comment holds (all pending without a
    readable marker), not the status's own.
    """

    issue: int
    status: Status
    change: Change | None = None
    create: bool = False


# GitHub, through `gh`

LABELS = {
    READY: ("0e8a16", "The dispatcher may take it (opened by its user, not blocked)"),
    IN_PROGRESS: ("fbca04", "A dispatcher session is working on it"),
    IN_REVIEW: ("1d76db", "A pull request is open; its required checks don't all pass yet"),
    READY_TO_MERGE: ("5319e7", "A pull request is open and its required checks pass"),
    NEEDS_ATTENTION: ("d93f0b", "The session ended without a pull request; see the comment"),
    PAUSED: ("c5def5", "The session hit the usage limit; it resumes when the limit is back"),
}
ISSUES = """query($owner: String!, $name: String!, $login: String!, $label: String!) {
  repository(owner: $owner, name: $name) {
    issues(first: 100, states: OPEN, filterBy: {createdBy: $login, labels: [$label]},
           orderBy: {field: CREATED_AT, direction: ASC}) {
      nodes {
        number
        title
        labels(first: 30) { nodes { name } }
        issueDependenciesSummary { blockedBy }
        closedByPullRequestsReferences(first: 10) {
          nodes { number url state isCrossRepository }
        }
      }
    }
  }
}"""
LINKED = """query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      closedByPullRequestsReferences(first: 10) { nodes { number isCrossRepository } }
    }
  }
}"""
CLOSING = r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?):?\s+#{}\b"


class GhError(Exception):
    """A `gh` call failed; the message carries its stderr."""


type GhRunner = Callable[[list[str]], tuple[int, str, str]]


def run_gh(args: list[str]) -> tuple[int, str, str]:
    """Run `gh` with these arguments: exit code, stdout, stderr."""
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    return result.returncode, result.stdout, result.stderr


def comment_id(value: Any) -> int:
    """A REST comment's numeric id; anything else is no id."""
    if type(value) is not int:
        raise TypeError(f"comment id {value!r}")
    return value


class GitHub:
    """Every read and write the dispatcher makes on GitHub, as thin `gh` calls."""

    def __init__(self, run: GhRunner = run_gh) -> None:
        """Call `gh` through `run`."""
        self.run = run
        self._login: str | None = None

    def _ok(self, args: list[str]) -> str:
        code, out, err = self.run(args)
        if code:
            raise GhError(f"gh {' '.join(args[:2])}: {err.strip() or f'exit {code}'}")
        return out

    def _graphql(self, query: str, **fields: str | int) -> dict[str, Any]:
        # gh fills {owner} and {repo} from this checkout's remote
        args = ["api", "graphql", "-f", f"query={query}", "-F", "owner={owner}", "-F",
                "name={repo}"]
        for key, value in fields.items():
            args += ["-F", f"{key}={value}"]
        data: dict[str, Any] = json.loads(self._ok(args))["data"]["repository"]
        return data

    def login(self) -> str:
        """The user `gh` is logged in as."""
        if self._login is None:
            self._login = self._ok(["api", "user", "-q", ".login"]).strip()
        return self._login

    def issues(self, label: str) -> list[tuple[Issue, tuple[PullRequest, ...]]]:
        """The user's open issues with this label, oldest first, each with its linked open PRs.

        Only this repository's pull requests count: the repository is public, so a fork's
        pull request can say `Closes #N` too.
        """
        found = self._graphql(ISSUES, login=self.login(), label=label)["issues"]["nodes"]
        return [(Issue(node["number"],
                       frozenset(tag["name"] for tag in node["labels"]["nodes"]),
                       node["issueDependenciesSummary"]["blockedBy"],
                       node.get("title") or ""),
                 tuple(PullRequest(pr["number"], pr["url"])
                       for pr in node["closedByPullRequestsReferences"]["nodes"]
                       if pr["state"] == "OPEN" and not pr["isCrossRepository"]))
                for node in found]

    def linked(self, issue: int) -> frozenset[int]:
        """This repository's pull requests GitHub links to an issue (a closing keyword)."""
        found = self._graphql(LINKED, number=issue)["issue"]["closedByPullRequestsReferences"]
        return frozenset(pr["number"] for pr in found["nodes"] if not pr["isCrossRepository"])

    def head(self, branch: str) -> tuple[PullRequest, ...]:
        """This repository's open pull requests from a branch: `--head` matches forks' too."""
        found = json.loads(self._ok(["pr", "list", "--head", branch, "--state", "open",
                                     "--json", "number,url,isCrossRepository"]))
        return tuple(PullRequest(pr["number"], pr["url"])
                     for pr in found if not pr["isCrossRepository"])

    def passing(self, pr: int) -> bool:
        """Whether every required check passes (`gh pr checks` exits 8 while some are pending)."""
        code, _, _ = self.run(["pr", "checks", str(pr), "--required"])
        return code == 0

    def ensure_labels(self) -> list[str]:
        """Create the dispatcher's labels that the repository doesn't have yet; say which."""
        present = {label["name"]
                   for label in json.loads(self._ok(["label", "list", "--limit", "500",
                                                     "--json", "name"]))}
        created = []
        for name, (color, description) in LABELS.items():
            if name not in present:
                self._ok(["label", "create", name, "--color", color, "--description",
                          description])
                created.append(name)
        return created

    def marker(self, issue: int) -> Marker | None:
        """A paused issue's newest valid marker among the `gh` user's comments, if any.

        The repository is public: anyone else's marker could name a session to resume.
        """
        login = self.login()
        comments = json.loads(self._ok(["issue", "view", str(issue), "--json",
                                        "comments"]))["comments"]
        found = [marker for comment in comments  # oldest first
                 if (comment.get("author") or {}).get("login") == login
                 and (marker := marker_of(comment.get("body") or "", issue))]
        return found[-1] if found else None

    def _read[T](self, args: list[str], read: Callable[[Any], T]) -> T:
        """What `read` makes of a `gh` call's JSON; output it cannot read is a GhError too."""
        out = self._ok(args)
        try:
            return read(json.loads(out))
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise GhError(f"gh {' '.join(args[:2])}: unreadable output: {error!r}") from error

    def status_comment(self, issue: int) -> tuple[int, str] | None:
        """An issue's status comment, as its id and body: the `gh` user's newest with a marker.

        The repository is public: anyone else's marker could take the comment's place.
        """
        login = self.login()

        def newest(pages: Any) -> tuple[int, str] | None:
            if not isinstance(pages, list) or not all(isinstance(page, list) for page in pages):
                raise TypeError("not an array of pages")
            found = [(comment_id(comment["id"]), comment["body"])
                     for page in pages for comment in page  # oldest first
                     if (comment.get("user") or {}).get("login") == login
                     and status_marks(comment.get("body") or "") is not None]
            return found[-1] if found else None
        return self._read(["api", "--paginate", "--slurp",
                           f"repos/{{owner}}/{{repo}}/issues/{issue}/comments"], newest)

    def post_status(self, issue: int, body: str) -> int:
        """Create an issue's status comment; its id."""
        return self._read(["api", "--method", "POST",
                           f"repos/{{owner}}/{{repo}}/issues/{issue}/comments",
                           "-f", f"body={body}"], lambda reply: comment_id(reply["id"]))

    def edit_status(self, comment: int, body: str) -> None:
        """Replace a status comment's body (an edit notifies no one)."""
        self._ok(["api", "--method", "PATCH", f"repos/{{owner}}/{{repo}}/issues/comments/{comment}",
                  "-f", f"body={body}"])

    def move(self, move: Move) -> None:
        """Swap the labels, then comment; a comment-first move comments, then swaps."""
        args = ["issue", "edit", str(move.issue)]
        for label in move.remove:
            args += ["--remove-label", label]
        for label in move.add:
            args += ["--add-label", label]
        post = ["issue", "comment", str(move.issue), "--body", move.comment] if move.comment else None
        if post and move.comment_first:
            self._ok(post)
        self._ok(args)
        if post and not move.comment_first:
            self._ok(post)

    def link(self, link: Link) -> None:
        """Append `Closes #issue` to the pull request's body unless a closing keyword is there."""
        body = self._ok(["pr", "view", str(link.pr), "--json", "body", "-q", ".body"])
        if not re.search(CLOSING.format(link.issue), body, re.IGNORECASE):
            self._ok(["pr", "edit", str(link.pr), "--body",
                      f"{body.rstrip()}\n\nCloses #{link.issue}\n"])


class Board:
    """Each issue's one status comment: looked up once per run, written when its text changes."""

    def __init__(self, gh: GitHub) -> None:
        """Read and write the comments through `gh`."""
        self.gh = gh
        self._comments: dict[int, tuple[int, str] | None] = {}  # issue → its comment's id, body

    def _comment(self, issue: int) -> tuple[int, str] | None:
        if issue not in self._comments:
            self._comments[issue] = self.gh.status_comment(issue)
        return self._comments[issue]

    def marks(self, issue: int) -> tuple[str, ...] | None:
        """The marks the issue's status comment holds; None without one."""
        comment = self._comment(issue)
        return status_marks(comment[1]) if comment else None

    def report(self, issue: int, status: Status, now: float, create: bool) -> None:
        """Show `status` on the issue: edit its comment, or, only if `create`, post one.

        A failed write forgets the comment, so the next report lists the comments again: the
        author may have deleted it, or a create whose reply was lost may have landed.
        """
        body = status.body(now)
        comment = self._comment(issue)
        if comment is not None and same_status(comment[1], body):
            return
        if comment is None and not create:
            return
        try:
            if comment is None:
                self._comments[issue] = (self.gh.post_status(issue, body), body)
            else:
                self.gh.edit_status(comment[0], body)
                self._comments[issue] = (comment[0], body)
        except GhError:
            del self._comments[issue]
            raise


# Sessions: a worktree, a headless lfg run in it, its log

WORKTREES = ".claude/worktrees"
STATE = "tools/dispatcher/.state"  # logs, session records and the lock, from the checkout's root
RECORD = re.compile(r"issue-(\d+)\.json")  # a session record's file name, under STATE/sessions
GONE = -1  # what a followed process's poll() says once it is gone: its exit code is unknown
GRACE = 10.0  # seconds a session gets to exit after terminate, before kill
CLOSES = ("The pull request body must contain the line `Closes #{issue}`, "
          "so merging it closes the issue.")
PROMPT = "/compound-engineering:lfg #{issue}\n\n" + CLOSES
CONTINUE = " Continue `/compound-engineering:lfg #{issue}` where it stopped.\n\n" + CLOSES
RESUME_PROMPTS = {  # by what paused the session
    LIMIT: "The Claude usage limit that stopped this session has reset." + CONTINUE,
    INTERRUPTED: "This session was interrupted: its process ended before it finished." + CONTINUE,
    STOPPED: "This session was stopped with `dispatcher.py stop`." + CONTINUE}
LIMIT_TEXT = re.compile(r"hit your .*limit|usage limit reached", re.IGNORECASE)
FLAGS = ["--permission-mode", "auto", "--output-format", "stream-json", "--verbose"]
ISSUE_FOLDER = re.compile(r"issue-(\d+)(-\d+)?")


class Process(Protocol):
    """What the dispatcher needs of a running `claude`: a `subprocess.Popen`, or a `Followed`."""

    pid: int
    returncode: int | None

    def poll(self) -> int | None:
        """None while running; once it exited, its exit code (`GONE` when no one can know it)."""

    def terminate(self) -> None:
        """Ask it to exit."""

    def kill(self) -> None:
        """Make it exit."""

    def wait(self, timeout: float | None = None) -> int:
        """Wait for its exit code."""


@dataclass(frozen=True)
class Running:
    """A session the dispatcher started, or one an earlier dispatcher started, followed again."""

    issue: int
    branch: str
    worktree: Path
    log: Path
    process: Process
    since: int = 0  # where this session's output starts in the issue's log
    started: float = 0.0  # time.time() when it started
    resumed: Marker | None = None  # the marker it was resumed from
    start_marks: tuple[str, ...] = UNSTARTED  # the checklist a resume continues from


@dataclass(frozen=True)
class Record:
    """What a session leaves on disk, so a later dispatcher can follow it (one file per issue).

    `start` is its process's start time as `run_ps` read it (None: it had exited already), so a
    process that merely reuses the PID is never taken for it. `stopped`: `dispatcher.py stop`
    ended it.
    """

    issue: int
    pid: int
    start: str | None
    branch: str
    worktree: Path
    log: Path
    since: int
    started: float
    resumed: Marker | None = None
    start_marks: tuple[str, ...] = UNSTARTED
    stopped: bool = False

    def text(self) -> str:
        """The record as its file holds it."""
        return json.dumps({"issue": self.issue, "pid": self.pid, "start": self.start,
                           "branch": self.branch, "worktree": str(self.worktree),
                           "log": str(self.log), "since": self.since, "started": self.started,
                           "resumed": self.resumed.fields() if self.resumed else None,
                           "start_marks": list(self.start_marks), "stopped": self.stopped})


def record_of(text: str, issue: int) -> Record | None:
    """The record a file holds, if it is this issue's with every field of its kind.

    Records are renamed into place whole, so only outside damage fails this; the PID must be
    positive, as signalling group 0 would signal the dispatcher's own.
    """
    try:
        data = json.loads(text)
        resumed = data["resumed"]
        record = Record(data["issue"], data["pid"], data["start"], data["branch"],
                        Path(data["worktree"]), Path(data["log"]), data["since"], data["started"],
                        None if resumed is None else marker_from(resumed, issue),
                        tuple(data["start_marks"]),
                        data["stopped"])
    except (ValueError, KeyError, TypeError):
        return None
    number = (int, float)
    valid = (record.issue == issue and type(record.pid) is int and record.pid > 0
             and (record.start is None or isinstance(record.start, str))
             and branch_of(record.branch, issue) and type(record.since) is int
             and record.since >= 0 and isinstance(record.started, number)
             and not isinstance(record.started, bool) and (resumed is None) == (record.resumed is None)
             and len(record.start_marks) == len(STAGES)
             and all(isinstance(mark, str) and mark in MARK_SIGNS for mark in record.start_marks)
             and isinstance(record.stopped, bool))
    return record if valid else None


def run_ps(pid: int) -> str | None:
    """A process's start time as `ps -o lstart=` prints it; None when no process has the PID.

    `lstart` follows the reader's time zone and locale, and a laptop's zone can change while a
    session runs: read in UTC and the C locale, the text stays the same for the process's life.
    """
    result = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True,
                            text=True, check=False,
                            env={**os.environ, "TZ": "UTC", "LC_ALL": "C"})
    return result.stdout.strip() or None


class Followed:
    """A session an earlier dispatcher started: not this process's child, followed by its PID.

    It runs while the PID's process has the recorded start time. Its exit code is never known,
    so `returncode` stays None. Signals go to its process group (the session started one of
    its own), so the tools it spawned end with it; a group gone is never signalled.
    """

    def __init__(self, pid: int, start: str | None, ps: Callable[[int], str | None],
                 killpg: Callable[[int, int], None]) -> None:
        """The process `pid`, started at `start`; read through `ps`, signalled through `killpg`."""
        self.pid = pid
        self.start = start
        self.ps = ps
        self.killpg = killpg
        self.returncode: int | None = None

    def poll(self) -> int | None:
        """None while it runs; `GONE` once no process with its PID and start time does."""
        found = self.ps(self.pid)
        return None if found is not None and found == self.start else GONE

    def _signal(self, signum: int) -> None:
        if self.poll() is None:
            with contextlib.suppress(ProcessLookupError):  # it ended since the check
                self.killpg(self.pid, signum)

    def terminate(self) -> None:
        """Ask its process group to exit."""
        self._signal(signal.SIGTERM)

    def kill(self) -> None:
        """Make its process group exit."""
        self._signal(signal.SIGKILL)

    def wait(self, timeout: float | None = None) -> int:
        """Check until it is gone (`GONE`); raise `subprocess.TimeoutExpired` past `timeout`."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while (code := self.poll()) is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(f"PID {self.pid}", timeout or 0.0)
            time.sleep(0.1 if deadline is None else min(0.1, max(deadline - time.monotonic(), 0)))
        return code


def reason_of(events: list[dict[str, Any]], running: Running) -> str:
    """Why a session ended: its final result's text, else its exit code."""
    for event in reversed(events):
        if event.get("type") == "result" and event.get("result"):
            return str(event["result"]).strip()[:2000]
    return f"the session exited with code {running.process.returncode} and no final result"


def limit_of(events: list[dict[str, Any]], running: Running) -> Marker | None:
    """The marker when the usage limit stopped the session, else None.

    Only top-level events count, never the text inside them, which may quote the limit. The
    final result must be absent or an error, and the last rate limit event `rejected` or that
    result's text name the limit; the reset is that rejected event's `resetsAt`.
    """
    session: str | None = None
    status: object = None
    resets: object = None
    final: dict[str, Any] | None = None
    for event in events:
        if isinstance(event.get("session_id"), str):
            session = event["session_id"]
        if event.get("type") == "rate_limit_event":
            info = event.get("rate_limit_info")
            info = info if isinstance(info, dict) else {}
            status, resets = info.get("status"), info.get("resetsAt")
        elif event.get("type") == "result":
            final = event
    if session is None or (final is not None and not final.get("is_error")):
        return None
    named = final is not None and bool(LIMIT_TEXT.search(str(final.get("result") or "")))
    if status != "rejected" and not named:
        return None
    reset = (int(resets) if status == "rejected" and isinstance(resets, int | float)
             and not isinstance(resets, bool) else None)
    return Marker(session, running.branch, reset)


def progress_of(events: list[dict[str, Any]], start_marks: tuple[str, ...]) -> Progress:
    """The checklist and the last sentence after these events, from where `start_marks` left off.

    Only the main thread's assistant events count, never a sub-agent's skills or words. A stage
    is entered by a `Skill` call to one of its `SKILLS`, or by a starting mark done, current or
    paused. The furthest stage entered is current, so it never moves back; the ones before it
    are done if entered, else skipped; the ones after it pending. Before any, the plan is
    current. The sentence is the last text, on one line, at most `LATEST` characters.
    """
    entered = {index for index, mark in enumerate(start_marks)
               if mark in ("done", "current", "paused")}
    latest: str | None = None
    for event in events:
        if event.get("type") != "assistant" or event.get("parent_tool_use_id") is not None:
            continue
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "Skill":
                arguments = block.get("input")
                skill = arguments.get("skill") if isinstance(arguments, dict) else None
                stage = SKILLS.get(skill.rpartition(":")[2]) if isinstance(skill, str) else None
                if stage:
                    entered.add(STAGES.index(stage))
            elif (block.get("type") == "text"
                  and (text := " ".join(str(block.get("text") or "").split()))):
                latest = text if len(text) <= LATEST else text[:LATEST - 1] + "…"
    current = max(entered, default=0)
    marks = tuple("current" if index == current else "pending" if index > current
                  else "done" if index in entered else "skipped" for index in range(len(STAGES)))
    return Progress(marks, latest)


def run_git(args: list[str]) -> str:
    """Run `git` in this checkout; raise on failure."""
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True,
                          cwd=ROOT).stdout


class Sessions:
    """Start, read, record and end the lfg sessions, each in its own worktree."""

    def __init__(self, root: Path, git: Callable[[list[str]], str] = run_git,
                 spawn: Callable[..., Process] = subprocess.Popen,
                 ps: Callable[[int], str | None] = run_ps,
                 killpg: Callable[[int, int], None] = os.killpg) -> None:
        """Worktrees under `root` through `git`, sessions through `spawn`, `ps` and `killpg`.

        `ps` reads a process's start time; `killpg` signals a followed session's process group.
        """
        self.root = root
        self.git = git
        self.spawn = spawn
        self.ps = ps
        self.killpg = killpg

    def _name(self, issue: int) -> str:
        """`issue-N`, suffixed `-2`, `-3`… while the folder or the branch exists."""
        suffix = 1
        while True:
            name = f"issue-{issue}" + (f"-{suffix}" if suffix > 1 else "")
            if (not (self.root / WORKTREES / name).exists()
                    and not self.git(["branch", "--list", name]).strip()):
                return name
            suffix += 1

    def start(self, issue: int) -> Running:
        """A new worktree from the latest origin/main, and lfg running headless in it."""
        self.git(["fetch", "origin", "main"])
        name = self._name(issue)
        worktree = self.root / WORKTREES / name
        self.git(["worktree", "add", "-b", name, str(worktree), "origin/main"])
        return self._run(issue, name, worktree, [PROMPT.format(issue=issue)])

    def resume(self, issue: int, marker: Marker,
               start_marks: tuple[str, ...] = UNSTARTED) -> Running:
        """The paused conversation resumed headless in its kept worktree, told why it stopped.

        Its checklist continues from `start_marks`. A missing worktree raises before anything
        starts.
        """
        worktree = self.root / WORKTREES / marker.branch
        if not worktree.is_dir():
            raise FileNotFoundError(f"the worktree {worktree} is gone")
        return self._run(issue, marker.branch, worktree,
                         ["--resume", marker.session,
                          RESUME_PROMPTS[marker.cause].format(issue=issue)], marker, start_marks)

    def _run(self, issue: int, branch: str, worktree: Path, args: list[str],
             resumed: Marker | None = None,
             start_marks: tuple[str, ...] = UNSTARTED) -> Running:
        """`claude -p` with these arguments in the worktree, appending to the issue's log.

        Its record is written once it runs; one that can't be written ends it and raises: a
        session no later dispatcher could follow or stop must not run on.
        """
        log = self.root / STATE / "logs" / f"issue-{issue}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as output:
            since = output.tell()
            process = self.spawn(["claude", "-p", *args, *FLAGS],
                                 cwd=worktree, stdin=subprocess.DEVNULL, stdout=output,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        running = Running(issue, branch, worktree, log, process, since, time.time(), resumed,
                          start_marks)
        try:
            self._write(Record(issue, process.pid, self.ps(process.pid), branch, worktree, log,
                               since, running.started, resumed, start_marks))
        except OSError as error:
            self.end([running])
            raise OSError(f"its session record could not be written: {error}") from error
        return running

    def _record(self, issue: int) -> Path:
        return self.root / STATE / "sessions" / f"issue-{issue}.json"

    def _write(self, record: Record) -> None:
        """Write the record to a temporary file, then rename it into place: never half of one."""
        path = self._record(record.issue)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(record.text())
        temporary.replace(path)

    def records(self) -> dict[int, Record | None]:
        """Every session record, by issue; None for one that can't be read."""
        found: dict[int, Record | None] = {}
        folder = self.root / STATE / "sessions"
        for path in sorted(folder.iterdir()) if folder.is_dir() else []:
            if match := RECORD.fullmatch(path.name):
                issue = int(match[1])
                try:
                    found[issue] = record_of(path.read_text(), issue)
                except (OSError, UnicodeDecodeError):
                    found[issue] = None
        return found

    def follow(self, record: Record) -> Running:
        """The session a record names, followed again by its PID and start time (`Followed`)."""
        return Running(record.issue, record.branch, record.worktree, record.log,
                       Followed(record.pid, record.start, self.ps, self.killpg), record.since,
                       record.started, record.resumed, record.start_marks)

    def mark_stopped(self, record: Record) -> Record:
        """Write the record again, marked stopped; the record as now written."""
        stopped = replace(record, stopped=True)
        self._write(stopped)
        return stopped

    def forget(self, issue: int) -> None:
        """Remove the issue's session record, if there is one."""
        self._record(issue).unlink(missing_ok=True)

    def _events(self, running: Running) -> list[dict[str, Any]]:
        """This session's part of the log as its top-level `stream-json` events, in order.

        An earlier attempt's output, before `since`, is not this session's.
        """
        try:
            with running.log.open("rb") as log:
                log.seek(running.since)
                lines = log.read().decode(errors="replace").splitlines()
        except FileNotFoundError:
            lines = []
        events = []
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events

    def ending(self, running: Running) -> tuple[str, Marker | None, Progress]:
        """Why a session ended, its marker when the usage limit stopped it, and where it stood.

        One read of the log; the progress continues from the marks its resume started from.
        """
        events = self._events(running)
        return (reason_of(events, running), limit_of(events, running),
                progress_of(events, running.start_marks))

    def progress(self, running: Running, start_marks: tuple[str, ...]) -> Progress:
        """Where a running session stands, from its part of the log and these starting marks."""
        return progress_of(self._events(running), start_marks)

    def end(self, sessions: Iterable[Running]) -> None:
        """Terminate the sessions; kill those still running once the grace period is over."""
        processes = [running.process for running in sessions]
        for process in processes:
            process.terminate()
        deadline = time.monotonic() + GRACE
        for process in processes:
            try:
                process.wait(max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def worktrees(self) -> dict[int, list[str]]:
        """The worktrees named after an issue (`issue-N`, `issue-N-2`…), by issue."""
        found: dict[int, list[str]] = {}
        for line in self.git(["worktree", "list", "--porcelain"]).splitlines():
            path = line.removeprefix("worktree ")
            if path != line and (match := ISSUE_FOLDER.fullmatch(Path(path).name)):
                found.setdefault(int(match[1]), []).append(path)
        return found


# The command

SESSIONS = 2
EVERY = 300


def stamp(line: str) -> None:
    """Print a progress line with the time, at once: someone may be watching the terminal."""
    print(f"{time.strftime('%H:%M:%S')} {line}", flush=True)


class Dispatcher:
    """Applies each poll's actions through GitHub and the sessions; owns the running sessions."""

    def __init__(self, gh: GitHub, sessions: Sessions, slots: int,
                 say: Callable[[str], None] = stamp,
                 clock: Callable[[], float] = time.time) -> None:
        """Up to `slots` sessions; progress lines through `say`; the wall clock through `clock`."""
        self.gh = gh
        self.board = Board(gh)  # each issue's status comment
        self.sessions = sessions
        self.slots = slots
        self.say = say
        self.clock = clock
        self.hold = Hold()  # starts wait while the usage limit is spent
        self.running: dict[int, Running] = {}
        self.branches: dict[int, str] = {}  # issues in review: the branch their session pushed
        self.pending: list[Action] = []  # failed actions no later poll would redo: the next's
        self.judged: set[int] = set()  # ended sessions whose records go once nothing is pending

    def start(self) -> None:
        """Say what it watches, create the missing labels, mark the issues left in progress.

        Each one's status comment fails the stage it held; a failure to read or write it is
        reported, waits in `pending` for the first poll, and the start goes on. The hold comes
        back from the paused issues' markers; one without a valid marker is left to the first
        resume, which moves it to needs attention.
        """
        self.say(f"dispatcher: watching the open issues {self.gh.login()} opened and labelled "
                 f"`ready`, up to {self.slots} sessions at once")
        created = self.gh.ensure_labels()
        self.say("dispatcher: labels: " + ("; ".join(f"created the label `{name}`"
                                                     for name in created)
                                           or f"all {len(LABELS)} in place"))
        stranded = [issue for issue, _ in self.gh.issues(IN_PROGRESS)]
        if not stranded:
            self.say("dispatcher: no issue left in progress by an earlier run")
        for issue in stranded:
            self.say(f"dispatcher: #{issue.number} was left in progress with no session running:"
                     " it needs attention")
        for action in orphans(stranded, self.sessions.worktrees() if stranded else {},
                              self.sessions.root):
            if isinstance(action, Report):
                self.final(action)  # no later poll reads an issue that needs attention
            else:
                self.apply(action)
        now = self.clock()
        markers = [marker for issue, _ in self.gh.issues(PAUSED)
                   if (marker := self.gh.marker(issue.number))]
        self.held(restore(markers, now))

    def snapshot(self) -> tuple[Snapshot, list[Running]]:
        """Read GitHub: ended sessions' pull requests, issues in review, ready and paused ones."""
        over = [running for running in self.running.values() if running.process.poll() is not None]
        ended = [self.read(running) for running in over]
        reviews = []
        for issue, prs in self.gh.issues(IN_REVIEW):
            if not prs and issue.number in self.branches:
                prs = self.gh.head(self.branches[issue.number])
            reviews.append(Review(issue.number, any(self.gh.passing(pr.number) for pr in prs)))
        ready = tuple(issue for issue, _ in self.gh.issues(READY))
        paused = tuple(issue for issue, _ in self.gh.issues(PAUSED))
        return Snapshot(tuple(ended), tuple(reviews), ready, paused), over

    def read(self, running: Running) -> Ended:
        """An ended session with what GitHub says of its branch; one with a PR is remembered.

        Its log says where it stood and, without a pull request, why it ended and whether the
        usage limit stopped it.
        """
        prs = self.gh.head(running.branch)
        reason, limit, progress = self.sessions.ending(running)
        if prs:
            reason, limit = "", None  # judged by its pull request alone
        session = Ended(running.issue, str(running.worktree), str(running.log), reason, prs,
                        self.gh.linked(running.issue) if prs else frozenset(), limit,
                        running.resumed, progress)
        if prs:
            self.branches[running.issue] = running.branch
        return session

    def poll(self) -> None:
        """One poll: retry the failed verdicts, read, hold at the limit, decide, apply, report.

        A failed read skips the rest of the poll: ended sessions wait for the next one. The
        clock is read once: an unknown reset holds until this `now`, so this poll's tick too.
        After the moves, each session still running and each ready issue left waiting is
        reported; the next poll reports them again, so a failed report is only said.
        """
        now = self.clock()
        self.say("dispatcher: poll: reading GitHub...")
        self.retry()
        try:
            snapshot, over = self.snapshot()
        except (GhError, ValueError, KeyError) as error:
            self.say(f"dispatcher: poll skipped: {error}")
            return
        for running in over:
            del self.running[running.issue]
            self.say(f"dispatcher: #{running.issue} session ended "
                     f"(exit code {running.process.returncode}), log {running.log}")
        hold = self.hold
        for session in snapshot.ended:
            if session.limit and session.limit.cause == LIMIT:  # only the usage limit holds
                hold = hold.extend(session.limit.reset, now)
        if hold != self.hold:
            self.held(hold)
        blocked = sum(1 for issue in snapshot.ready if issue.blocked)
        self.say(f"dispatcher: poll: {len(snapshot.ready)} ready ({blocked} blocked), "
                 f"{len(snapshot.paused)} paused, {len(self.running)} running, "
                 f"{len(snapshot.reviews)} in review")
        for running in self.running.values():
            minutes = int((now - running.started) // 60)
            self.say(f"dispatcher: #{running.issue} still running ({minutes} min), "
                     f"log {running.log}")
        for review in snapshot.reviews:
            self.say(f"dispatcher: #{review.issue} in review: "
                     + ("its required checks pass" if review.passing
                        else "its required checks don't all pass yet"))
        self.settle(snapshot.ended)
        actions = tick(snapshot, set(self.running), self.slots, now, self.hold)
        picked = [action.issue for action in actions if isinstance(action, Dispatch | Resume)]
        held = self.hold.holds(now)
        for line in queue_lines(snapshot.ready, set(self.running), picked, self.slots, held):
            self.say(f"dispatcher: {line}")
        for action in actions:
            if isinstance(action, Report) and action.status.state == READY_TO_MERGE:
                self.final(action)  # no later poll reads an issue ready to merge
            else:
                self.apply(action)
        for running in list(self.running.values()):
            if running.issue not in picked:
                self.apply(self.running_report(running))
        until = None if self.hold.probe else self.hold.until
        for issue in snapshot.ready:
            if (READY in issue.labels and not issue.labels & {IN_PROGRESS, PAUSED}
                    and issue.number not in self.running and issue.number not in picked):
                self.apply(Report(issue.number,
                                  Status(QUEUED, reason=waiting(issue.blocked, held, until)),
                                  create=True))
        if not self.hold.holds(now):
            self.hold = Hold()

    def held(self, hold: Hold) -> None:
        """Take this hold, and say until when no session starts."""
        self.hold = hold
        if hold.probe:
            self.say("dispatcher: the Claude usage limit is spent and its reset is unknown; "
                     "one session is tried at the next poll")
        elif hold.until is not None:
            self.say("dispatcher: the Claude usage limit is spent; no session starts until "
                     f"{local_time(hold.until)}")

    def settle(self, ended: Iterable[Ended]) -> None:
        """Apply the ended sessions' verdicts: no later poll judges them, so a failed one waits.

        Each one's record goes once its verdict is applied in full.
        """
        for session in ended:
            for action in judge(session, self.sessions.root):
                self.final(action)
            self.judged.add(session.issue)
        self.tidy()

    def retry(self) -> None:
        """Apply the actions that failed before; the records whose verdicts are now in full go."""
        self.pending = [action for action in self.pending if not self.apply(action)]
        self.tidy()

    def tidy(self) -> None:
        """Remove the records of the judged sessions with nothing pending for their issues.

        A record kept survives a restart, so its session is judged again.
        """
        waiting = {action.issue for action in self.pending}
        for issue in self.judged - waiting:
            self.sessions.forget(issue)
        self.judged &= waiting

    def final(self, action: Action) -> None:
        """Apply an action no later poll would redo: a failed one waits in `pending`."""
        if not self.apply(action):
            self.pending.append(action)

    def apply(self, action: Action) -> bool:
        """One action, and whether it went; a failed `gh` call is reported, the others still run."""
        try:
            match action:
                case Move():
                    self.gh.move(action)
                    self.say(f"dispatcher: #{action.issue} -> {', '.join(action.add)}")
                case Link():
                    self.gh.link(action)
                case Dispatch():
                    self.dispatch(action.issue)
                case Resume():
                    self.resume(action.issue)
                case Report():
                    status = action.status
                    if action.change is not None:
                        stored = self.board.marks(action.issue) or UNSTARTED
                        status = replace(status, marks=action.change(stored))
                    self.board.report(action.issue, status, self.clock(), action.create)
        except GhError as error:
            subject = f"#{action.issue} status" if isinstance(action, Report) else action
            self.say(f"dispatcher: {subject}: {error}")
            return False
        return True

    def running_report(self, running: Running) -> Report:
        """A live session's running report, from its log.

        Only a session this run dispatched may post the comment: a resumed one is edited.
        """
        progress = self.sessions.progress(running, running.start_marks)
        return Report(running.issue, Status(RUNNING, progress.marks, latest=progress.latest,
                                            started=running.started),
                      create=running.resumed is None)

    def places(self, running: Running) -> tuple[str, str]:
        """A comment's lines naming the session's worktree and log, under the checkout."""
        root = self.sessions.root
        return (f"Worktree: `{inside(running.worktree, root)}`",
                f"Log: `{inside(running.log, root)}`")

    def stopped_report(self, running: Running) -> Report:
        """An ended session GitHub couldn't be read for at stop: the stage its log reached fails."""
        marks = self.sessions.progress(running, running.start_marks).marks
        return Report(running.issue, Status(NEEDS_ATTENTION, marks_stopped(marks)))

    def dispatch(self, issue: int) -> None:
        """In progress, then a session, reported running; one that cannot start needs attention.

        A failed label swap raises before the session: the issue stays `ready` for the next poll.
        Dispatching may post the status comment.
        """
        self.gh.move(Move(issue, (READY, NEEDS_ATTENTION), (IN_PROGRESS,)))
        self.say(f"dispatcher: #{issue} -> {IN_PROGRESS}")
        self.say(f"dispatcher: #{issue}: fetching origin/main and creating its worktree...")
        try:
            running = self.sessions.start(issue)
        except (OSError, subprocess.CalledProcessError) as error:
            detail = (error.stderr if isinstance(error, subprocess.CalledProcessError)
                      and error.stderr else error)
            detail = unrooted(str(detail).strip(), self.sessions.root)
            self.apply(needs_attention(issue, f"the session could not start: {detail}"))
            self.final(Report(issue, Status(NEEDS_ATTENTION, marks_stopped(UNSTARTED)),
                              create=True))
            return
        self.running[issue] = running
        self.judged.discard(issue)  # its record is this session's now, not the last one's
        self.say(f"dispatcher: #{issue}: claude started (PID {running.process.pid}) in "
                 f"{running.worktree}, log {running.log}")
        self.apply(self.running_report(running))

    def resume(self, issue: int) -> None:
        """In progress, then the paused conversation; one that cannot resume needs attention.

        Without a valid marker there is nothing to resume. The checklist continues from the
        status comment's marks, which the session's record holds. A failed read or label swap
        raises before the session: the issue stays `paused` for the next poll.
        """
        marker = self.gh.marker(issue)
        if marker is None:
            self.apply(needs_attention(issue, "this issue is paused, but no pause record was "
                                       "found in its comments, so its session cannot resume.",
                                       remove=PAUSED))
            self.final(Report(issue, Status(NEEDS_ATTENTION), marks_stopped))
            return
        stored = self.board.marks(issue) or UNSTARTED
        self.gh.move(Move(issue, (PAUSED, READY, NEEDS_ATTENTION), (IN_PROGRESS,)))
        self.say(f"dispatcher: #{issue} -> {IN_PROGRESS}")
        try:
            running = self.sessions.resume(issue, marker, marks_resumed(stored))
        except OSError as error:
            self.apply(needs_attention(issue, "the paused session could not resume: "
                                       + unrooted(str(error), self.sessions.root)))
            self.final(Report(issue, Status(NEEDS_ATTENTION), marks_stopped))
            return
        self.running[issue] = running
        self.judged.discard(issue)  # its record is this session's now, not the last one's
        self.say(f"dispatcher: #{issue} resumed in {running.worktree}, log {running.log}")
        self.apply(self.running_report(running))

    def stop(self) -> None:
        """Leave: judge the sessions that already ended, as a poll would; leave the others running.

        The verdicts that failed at earlier polls get one last try: no poll follows, and a record
        whose verdict still fails stays for the next start. A session left running keeps its
        record, its label and its status comment: the next start follows it.
        """
        self.retry()
        for running in self.running.values():
            if running.process.poll() is None:
                self.say(f"dispatcher: #{running.issue} left running "
                         f"(PID {running.process.pid}), the next start follows it")
                continue
            try:
                self.settle([self.read(running)])
            except (GhError, ValueError, KeyError) as error:
                self.apply(needs_attention(running.issue, "the session ended, but the dispatcher "
                                           f"was stopped before GitHub could be read: {error}",
                                           *self.places(running)))
                self.apply(self.stopped_report(running))
        self.running.clear()


def alive(pid: int) -> bool:
    """Whether a process with this PID exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def take(lock: Path) -> bool:
    """Hold the lock for this process, unless a live dispatcher holds it."""
    lock.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            holder = lock.read_text().strip()
            if holder.isdigit() and alive(int(holder)):
                return False
            lock.unlink(missing_ok=True)  # a dead dispatcher's lock
            continue
        with os.fdopen(descriptor, "w") as file:
            file.write(str(os.getpid()))
        return True
    return False


def serve(boss: Dispatcher, every: float) -> None:
    """Poll every `every` seconds until SIGINT or SIGTERM, then leave (`Dispatcher.stop`).

    An error leaves too before it propagates: the sessions that ended are judged, the live
    ones keep running, and the next start follows them.
    """
    stopping = threading.Event()

    def stop(signum: int, frame: object) -> None:
        stopping.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        boss.start()
        boss.say(f"dispatcher: a poll every {every:g}s; Ctrl-C stops")
        while not stopping.is_set():
            boss.poll()
            if not stopping.is_set():
                upcoming = time.strftime("%H:%M:%S", time.localtime(time.time() + every))
                boss.say(f"dispatcher: next poll at {upcoming}")
            stopping.wait(every)
    finally:
        boss.say("dispatcher: stopping")
        boss.stop()


def main(argv: list[str]) -> int:
    """Run `run`; refuse when another dispatcher runs."""
    if len(argv) < 2 or argv[1] != "run":
        print(__doc__)
        return 2
    parser = argparse.ArgumentParser(prog="dispatcher.py run")
    parser.add_argument("--sessions", type=int, default=SESSIONS)
    parser.add_argument("--every", type=float, default=EVERY)
    options = parser.parse_args(argv[2:])
    lock = ROOT / STATE / "lock"
    if not take(lock):
        print(f"dispatcher: another dispatcher runs (PID {lock.read_text().strip()}); "
              f"stop it first, or remove {lock} if it is gone")
        return 1
    try:
        serve(Dispatcher(GitHub(), Sessions(ROOT), options.sessions), options.every)
    finally:
        lock.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
