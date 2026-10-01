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
usage limit stopped it). A pause holds every start until a minute past the limit's
reset, or, with no reset known, until the next poll tries one session. Past the hold,
paused issues resume first, oldest first: the same conversation, in the same worktree.
Every line it prints carries the time; each poll reports what it found. Logs and the
lock are in tools/dispatcher/.state/. Ctrl-C judges the sessions that ended, as a poll
would, then stops the others and marks their issues `needs attention`; paused issues
stay paused, and the next start resumes them from GitHub alone.
"""

import argparse
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
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
    """What resumes a paused session: its conversation, its branch, its reset (epoch seconds)."""

    session: str
    branch: str
    reset: int | None

    def line(self) -> str:
        """The hidden marker a pause comment ends with."""
        record = {"session": self.session, "branch": self.branch, "reset": self.reset}
        return f"<!-- {MARKER} {json.dumps(record)} -->"


MARKER_LINE = re.compile(rf"<!-- {MARKER} (\{{.*\}}) -->")
SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def marker_of(body: str, issue: int) -> Marker | None:
    """The marker on a comment's last line, if its session is a UUID and its branch this issue's.

    The session becomes a `claude --resume` argument, and the branch a folder's name.
    """
    lines = body.strip().splitlines()
    found = MARKER_LINE.fullmatch(lines[-1].strip()) if lines else None
    try:
        record = json.loads(found[1]) if found else None
    except ValueError:
        return None
    if not isinstance(record, dict):
        return None
    session, branch, reset = record.get("session"), record.get("branch"), record.get("reset")
    if (isinstance(session, str) and SESSION_ID.fullmatch(session)
            and isinstance(branch, str) and re.fullmatch(rf"issue-{issue}(-\d+)?", branch)
            and (reset is None or (isinstance(reset, int) and not isinstance(reset, bool)))):
        return Marker(session, branch, reset)
    return None


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


type Action = Move | Link | Dispatch | Resume


def local_time(epoch: float) -> str:
    """An epoch in this machine's local zone, with the zone's name."""
    return time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(epoch))


def needs_attention(issue: int, *paragraphs: str, remove: str = IN_PROGRESS) -> Move:
    """`remove` to needs attention, the comment saying why and how to queue it again."""
    return Move(issue, (remove,), (NEEDS_ATTENTION,),
                "\n\n".join(("Dispatcher: " + paragraphs[0], *paragraphs[1:],
                              "Add `ready` to queue it again.")))


def pause(session: Ended, limit: Marker) -> Move:
    """In progress to paused, the comment first carrying the marker, unless it is the resumed one."""
    if limit == session.resumed:
        return Move(session.issue, (IN_PROGRESS,), (PAUSED,))
    reset = (f"It resets at {local_time(limit.reset)}; the session resumes then."
             if limit.reset is not None else
             "The reset time is unknown; the dispatcher tries again at the next poll.")
    comment = "\n\n".join(("Dispatcher: the Claude usage limit stopped the session.", reset,
                            f"Session: `{limit.session}`", f"Worktree: `{session.worktree}`",
                            f"Log: `{session.log}`", limit.line()))
    return Move(session.issue, (IN_PROGRESS,), (PAUSED,), comment, comment_first=True)


def judge(session: Ended) -> list[Action]:
    """A session ended: in review with an open pull request, paused at the limit, else attention."""
    if not session.prs and session.limit:
        return [pause(session, session.limit)]
    if not session.prs:
        return [needs_attention(session.issue, "the session ended without a pull request.",
                                f"Reason: {session.reason}", f"Worktree: `{session.worktree}`",
                                f"Log: `{session.log}`")]
    pr = session.prs[0]
    actions: list[Action] = [Move(session.issue, (IN_PROGRESS,), (IN_REVIEW,),
                                  f"Dispatcher: pull request {pr.url} is open.")]
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
    blockers notwithstanding, and a probe starts one session only.
    """
    actions: list[Action] = [Move(review.issue, (IN_REVIEW,), (READY_TO_MERGE,))
                             for review in snapshot.reviews if review.passing]
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
    """At start, the hold the paused issues' markers make: none once every known reset is past."""
    hold = Hold()
    for marker in markers:
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


def orphans(in_progress: Iterable[Issue], worktrees: Mapping[int, list[str]]) -> list[Move]:
    """At start no session runs, so every issue in progress lost its session: it needs attention."""
    return [needs_attention(issue.number, "this issue was in progress with no session running "
                            "(the dispatcher was stopped or crashed).",
                            *(f"Worktree: `{path}`" for path in worktrees.get(issue.number, [])))
            for issue in in_progress]


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


# Sessions: a worktree, a headless lfg run in it, its log

WORKTREES = ".claude/worktrees"
STATE = "tools/dispatcher/.state"  # logs and the lock, from the checkout's root
GRACE = 10.0  # seconds a session gets to exit after terminate, before kill
PROMPT = ("/compound-engineering:lfg #{issue}\n\n"
          "The pull request body must contain the line `Closes #{issue}`, "
          "so merging it closes the issue.")
RESUME_PROMPT = ("The Claude usage limit that stopped this session has reset. Continue "
                 "`/compound-engineering:lfg #{issue}` where it stopped.\n\n"
                 "The pull request body must contain the line `Closes #{issue}`, "
                 "so merging it closes the issue.")
LIMIT_TEXT = re.compile(r"hit your .*limit|usage limit reached", re.IGNORECASE)
FLAGS = ["--permission-mode", "auto", "--output-format", "stream-json", "--verbose"]
ISSUE_FOLDER = re.compile(r"issue-(\d+)(-\d+)?")


class Process(Protocol):
    """What the dispatcher needs of a running `claude` (a `subprocess.Popen`)."""

    returncode: int | None

    def poll(self) -> int | None:
        """The exit code, or None while running."""

    def terminate(self) -> None:
        """Ask it to exit."""

    def kill(self) -> None:
        """Make it exit."""

    def wait(self, timeout: float | None = None) -> int:
        """Wait for its exit code."""


@dataclass(frozen=True)
class Running:
    """A session the dispatcher started."""

    issue: int
    branch: str
    worktree: Path
    log: Path
    process: Process
    since: int = 0  # where this session's output starts in the issue's log
    started: float = 0.0  # time.time() when it started
    resumed: Marker | None = None  # the marker it was resumed from


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


def run_git(args: list[str]) -> str:
    """Run `git` in this checkout; raise on failure."""
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True,
                          cwd=ROOT).stdout


class Sessions:
    """Start, read and end the lfg sessions, each in its own worktree."""

    def __init__(self, root: Path, git: Callable[[list[str]], str] = run_git,
                 spawn: Callable[..., Process] = subprocess.Popen) -> None:
        """Worktrees under `root`, through `git`; sessions through `spawn`."""
        self.root = root
        self.git = git
        self.spawn = spawn

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

    def resume(self, issue: int, marker: Marker) -> Running:
        """The paused conversation resumed headless in its kept worktree, told the limit is back.

        A missing worktree raises before anything starts.
        """
        worktree = self.root / WORKTREES / marker.branch
        if not worktree.is_dir():
            raise FileNotFoundError(f"the worktree {worktree} is gone")
        return self._run(issue, marker.branch, worktree,
                         ["--resume", marker.session, RESUME_PROMPT.format(issue=issue)], marker)

    def _run(self, issue: int, branch: str, worktree: Path, args: list[str],
             resumed: Marker | None = None) -> Running:
        """`claude -p` with these arguments in the worktree, appending to the issue's log."""
        log = self.root / STATE / "logs" / f"issue-{issue}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as output:
            since = output.tell()
            process = self.spawn(["claude", "-p", *args, *FLAGS],
                                 cwd=worktree, stdin=subprocess.DEVNULL, stdout=output,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        return Running(issue, branch, worktree, log, process, since, time.time(), resumed)

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

    def ending(self, running: Running) -> tuple[str, Marker | None]:
        """Why a session ended, and its marker when the usage limit stopped it, from one read."""
        events = self._events(running)
        return reason_of(events, running), limit_of(events, running)

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
        self.sessions = sessions
        self.slots = slots
        self.say = say
        self.clock = clock
        self.hold = Hold()  # starts wait while the usage limit is spent
        self.running: dict[int, Running] = {}
        self.branches: dict[int, str] = {}  # issues in review: the branch their session pushed
        self.pending: list[Action] = []  # ended sessions' verdicts that failed: the next poll's

    def start(self) -> None:
        """Say what it watches, create the missing labels, mark the issues left in progress.

        The hold comes back from the paused issues' markers; one without a valid marker is left
        to the first resume, which moves it to needs attention.
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
        for move in orphans(stranded, self.sessions.worktrees() if stranded else {}):
            self.apply(move)
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

        Without a pull request, its log says whether the usage limit stopped it.
        """
        prs = self.gh.head(running.branch)
        reason, limit = ("", None) if prs else self.sessions.ending(running)
        session = Ended(running.issue, str(running.worktree), str(running.log), reason, prs,
                        self.gh.linked(running.issue) if prs else frozenset(), limit,
                        running.resumed)
        if prs:
            self.branches[running.issue] = running.branch
        return session

    def poll(self) -> None:
        """One poll: retry the failed verdicts, read, hold at the limit, decide, apply.

        A failed read skips the rest of the poll: ended sessions wait for the next one. The
        clock is read once: an unknown reset holds until this `now`, so this poll's tick too.
        """
        now = self.clock()
        self.say("dispatcher: poll: reading GitHub...")
        self.pending = [action for action in self.pending if not self.apply(action)]
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
            if session.limit:
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
        for line in queue_lines(snapshot.ready, set(self.running), picked, self.slots,
                                self.hold.holds(now)):
            self.say(f"dispatcher: {line}")
        for action in actions:
            self.apply(action)
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
        """Apply the ended sessions' verdicts: no later poll judges them, so a failed one waits."""
        for session in ended:
            self.pending += [action for action in judge(session) if not self.apply(action)]

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
        except GhError as error:
            self.say(f"dispatcher: {action}: {error}")
            return False
        return True

    def dispatch(self, issue: int) -> None:
        """In progress, then a session; one that cannot start needs attention.

        A failed label swap raises before the session: the issue stays `ready` for the next poll.
        """
        self.gh.move(Move(issue, (READY, NEEDS_ATTENTION), (IN_PROGRESS,)))
        self.say(f"dispatcher: #{issue} -> {IN_PROGRESS}")
        self.say(f"dispatcher: #{issue}: fetching origin/main and creating its worktree...")
        try:
            running = self.sessions.start(issue)
        except (OSError, subprocess.CalledProcessError) as error:
            detail = (error.stderr if isinstance(error, subprocess.CalledProcessError)
                      and error.stderr else error)
            self.apply(needs_attention(issue,
                                       f"the session could not start: {str(detail).strip()}"))
            return
        self.running[issue] = running
        pid = getattr(running.process, "pid", "?")
        self.say(f"dispatcher: #{issue}: claude started (PID {pid}) in {running.worktree}, "
                 f"log {running.log}")

    def resume(self, issue: int) -> None:
        """In progress, then the paused conversation; one that cannot resume needs attention.

        Without a valid marker there is nothing to resume. A failed read or label swap raises
        before the session: the issue stays `paused` for the next poll.
        """
        marker = self.gh.marker(issue)
        if marker is None:
            self.apply(needs_attention(issue, "this issue is paused, but no pause record was "
                                       "found in its comments, so its session cannot resume.",
                                       remove=PAUSED))
            return
        self.gh.move(Move(issue, (PAUSED, READY, NEEDS_ATTENTION), (IN_PROGRESS,)))
        self.say(f"dispatcher: #{issue} -> {IN_PROGRESS}")
        try:
            running = self.sessions.resume(issue, marker)
        except OSError as error:
            self.apply(needs_attention(issue, f"the paused session could not resume: {error}"))
            return
        self.running[issue] = running
        self.say(f"dispatcher: #{issue} resumed in {running.worktree}, log {running.log}")

    def stop(self) -> None:
        """Judge the sessions that already ended, as a poll would; end the others and mark them.

        The verdicts that failed at earlier polls get one last try: no poll follows.
        """
        self.pending = [action for action in self.pending if not self.apply(action)]
        live: list[Running] = []
        ended: list[Running] = []
        for running in self.running.values():
            (live if running.process.poll() is None else ended).append(running)
        self.running.clear()
        for running in ended:
            try:
                self.settle([self.read(running)])
            except (GhError, ValueError, KeyError) as error:
                self.apply(needs_attention(running.issue, "the session ended, but the dispatcher "
                                           f"was stopped before GitHub could be read: {error}",
                                           f"Worktree: `{running.worktree}`",
                                           f"Log: `{running.log}`"))
        self.sessions.end(live)
        for running in live:
            self.apply(needs_attention(running.issue,
                                       "the dispatcher was stopped while the session ran.",
                                       f"Worktree: `{running.worktree}`", f"Log: `{running.log}`"))


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
    """Poll every `every` seconds until SIGINT or SIGTERM, then stop the sessions.

    An error stops them too before it propagates: no session is left running detached.
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
