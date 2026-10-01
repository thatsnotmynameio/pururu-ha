# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The author's ready issues become pull requests, one lfg session each.

Usage:
    python3 dispatcher.py run [--sessions N] [--every SECONDS]

Polls this repository's open issues opened by the user `gh` is logged in as and
labelled `ready`, oldest first, skipping any still blocked by an open issue. Each
one gets a new worktree from origin/main under .claude/worktrees/ and a headless
`claude -p` session running lfg; at most N run at once (default 2), and the poll
runs every SECONDS (default 300). Labels show where an issue stands: `in progress`,
then `in review` (a pull request is open) and `ready to merge` (its required checks
pass), or `needs attention` (the session ended without one). Logs and the lock are
in .dispatch/. Ctrl-C stops the sessions and marks their issues `needs attention`.
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
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parent
READY = "ready"
IN_PROGRESS = "in progress"
IN_REVIEW = "in review"
READY_TO_MERGE = "ready to merge"
NEEDS_ATTENTION = "needs attention"


@dataclass(frozen=True)
class Issue:
    """An open issue as the queue sees it: its labels and how many open issues block it."""

    number: int
    labels: frozenset[str] = frozenset()
    blocked: int = 0


@dataclass(frozen=True)
class PullRequest:
    """An open pull request."""

    number: int
    url: str


@dataclass(frozen=True)
class Ended:
    """A session whose process exited, with what GitHub says about its branch and issue."""

    issue: int
    worktree: str
    log: str
    reason: str
    prs: tuple[PullRequest, ...] = ()  # open pull requests from the session's branch
    linked: frozenset[int] = frozenset()  # the pull requests GitHub links to the issue


@dataclass(frozen=True)
class Review:
    """An issue `in review`, and whether an open pull request of it passes its required checks."""

    issue: int
    passing: bool


@dataclass(frozen=True)
class Snapshot:
    """What one poll read: ended sessions, issues in review, and the ready queue, oldest first."""

    ended: tuple[Ended, ...] = ()
    reviews: tuple[Review, ...] = ()
    ready: tuple[Issue, ...] = ()


@dataclass(frozen=True)
class Move:
    """Swap an issue's labels, then comment when there is something to say."""

    issue: int
    remove: tuple[str, ...]
    add: tuple[str, ...]
    comment: str | None = None


@dataclass(frozen=True)
class Link:
    """Add `Closes #issue` to a pull request's body, so merging it closes the issue."""

    pr: int
    issue: int


@dataclass(frozen=True)
class Dispatch:
    """Mark an issue in progress and start its session."""

    issue: int


type Action = Move | Link | Dispatch


def judge(session: Ended) -> list[Action]:
    """A session ended: in review when its branch has an open pull request, else needs attention."""
    if session.prs:
        pr = session.prs[0]
        moved: list[Action] = [Move(session.issue, (IN_PROGRESS,), (IN_REVIEW,),
                                    f"Dispatcher: pull request {pr.url} is open.")]
        return moved + ([] if pr.number in session.linked else [Link(pr.number, session.issue)])
    return [Move(session.issue, (IN_PROGRESS,), (NEEDS_ATTENTION,),
                 "Dispatcher: the session ended without a pull request.\n\n"
                 f"Reason: {session.reason}\n\nWorktree: `{session.worktree}`\n\n"
                 f"Log: `{session.log}`\n\nAdd `ready` to queue it again.")]


def pick(ready: Iterable[Issue], running: set[int], free: int) -> list[int]:
    """The first `free` ready issues not blocked, not running and not already in progress."""
    eligible = [issue.number for issue in ready
                if READY in issue.labels and IN_PROGRESS not in issue.labels
                and issue.number not in running and not issue.blocked]
    return eligible[:max(free, 0)]


def tick(snapshot: Snapshot, running: set[int], sessions: int) -> list[Action]:
    """One poll's actions: ended sessions judged, passing reviews promoted, free slots filled.

    `running` holds the issues whose sessions still run, the ended ones already out of it.
    """
    actions = [action for session in snapshot.ended for action in judge(session)]
    actions += [Move(review.issue, (IN_REVIEW,), (READY_TO_MERGE,))
                for review in snapshot.reviews if review.passing]
    actions += [Dispatch(number)
                for number in pick(snapshot.ready, running, sessions - len(running))]
    return actions


def orphans(in_progress: Iterable[Issue], worktrees: Mapping[int, list[str]]) -> list[Move]:
    """At start no session runs, so every issue in progress lost its session: it needs attention."""
    return [Move(issue.number, (IN_PROGRESS,), (NEEDS_ATTENTION,),
                 "Dispatcher: this issue was in progress with no session running "
                 "(the dispatcher was stopped or crashed).\n\n"
                 + "".join(f"Worktree: `{path}`\n\n" for path in worktrees.get(issue.number, []))
                 + "Add `ready` to queue it again.")
            for issue in in_progress]


# GitHub, through `gh`

LABELS = {
    READY: ("0e8a16", "The dispatcher may take it (opened by its user, not blocked)"),
    IN_PROGRESS: ("fbca04", "A dispatcher session is working on it"),
    IN_REVIEW: ("1d76db", "A pull request is open; its required checks don't all pass yet"),
    READY_TO_MERGE: ("5319e7", "A pull request is open and its required checks pass"),
    NEEDS_ATTENTION: ("d93f0b", "The session ended without a pull request; see the comment"),
}
ISSUES = """query($owner: String!, $name: String!, $login: String!, $label: String!) {
  repository(owner: $owner, name: $name) {
    issues(first: 100, states: OPEN, filterBy: {createdBy: $login, labels: [$label]},
           orderBy: {field: CREATED_AT, direction: ASC}) {
      nodes {
        number
        labels(first: 30) { nodes { name } }
        issueDependenciesSummary { blockedBy }
        closedByPullRequestsReferences(first: 10) { nodes { number url state } }
      }
    }
  }
}"""
LINKED = """query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) { closedByPullRequestsReferences(first: 10) { nodes { number } } }
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
        self._repo: tuple[str, str] | None = None
        self._login: str | None = None

    def _ok(self, args: list[str]) -> str:
        code, out, err = self.run(args)
        if code:
            raise GhError(f"gh {' '.join(args[:2])}: {err.strip() or f'exit {code}'}")
        return out

    def _graphql(self, query: str, **fields: str | int) -> dict[str, Any]:
        owner, name = self.repo()
        args = ["api", "graphql", "-f", f"query={query}", "-F", f"owner={owner}", "-F",
                f"name={name}"]
        for key, value in fields.items():
            args += ["-F", f"{key}={value}"]
        data: dict[str, Any] = json.loads(self._ok(args))["data"]["repository"]
        return data

    def repo(self) -> tuple[str, str]:
        """This checkout's GitHub owner and name."""
        if self._repo is None:
            owner, name = self._ok(
                ["repo", "view", "--json", "owner,name", "-q",
                 '.owner.login + "/" + .name']).strip().split("/")
            self._repo = owner, name
        return self._repo

    def login(self) -> str:
        """The user `gh` is logged in as."""
        if self._login is None:
            self._login = self._ok(["api", "user", "-q", ".login"]).strip()
        return self._login

    def issues(self, label: str) -> list[tuple[Issue, tuple[PullRequest, ...]]]:
        """The user's open issues with this label, oldest first, each with its linked open PRs."""
        found = self._graphql(ISSUES, login=self.login(), label=label)["issues"]["nodes"]
        return [(Issue(node["number"],
                       frozenset(label["name"] for label in node["labels"]["nodes"]),
                       node["issueDependenciesSummary"]["blockedBy"]),
                 tuple(PullRequest(pr["number"], pr["url"])
                       for pr in node["closedByPullRequestsReferences"]["nodes"]
                       if pr["state"] == "OPEN"))
                for node in found]

    def linked(self, issue: int) -> frozenset[int]:
        """The pull requests GitHub links to an issue (a closing keyword in their body)."""
        found = self._graphql(LINKED, number=issue)["issue"]["closedByPullRequestsReferences"]
        return frozenset(pr["number"] for pr in found["nodes"])

    def head(self, branch: str) -> tuple[PullRequest, ...]:
        """The open pull requests from a branch."""
        found = json.loads(self._ok(["pr", "list", "--head", branch, "--state", "open",
                                     "--json", "number,url"]))
        return tuple(PullRequest(pr["number"], pr["url"]) for pr in found)

    def passing(self, pr: int) -> bool:
        """Whether every required check passes (`gh pr checks` exits 8 while some are pending)."""
        code, _, _ = self.run(["pr", "checks", str(pr), "--required"])
        return code == 0

    def ensure_labels(self) -> None:
        """Create the dispatcher's labels that the repository doesn't have yet."""
        present = {label["name"]
                   for label in json.loads(self._ok(["label", "list", "--limit", "500",
                                                     "--json", "name"]))}
        for name, (color, description) in LABELS.items():
            if name not in present:
                self._ok(["label", "create", name, "--color", color, "--description",
                          description])

    def move(self, move: Move) -> None:
        """Swap the labels, then comment."""
        args = ["issue", "edit", str(move.issue)]
        for label in move.remove:
            args += ["--remove-label", label]
        for label in move.add:
            args += ["--add-label", label]
        self._ok(args)
        if move.comment:
            self._ok(["issue", "comment", str(move.issue), "--body", move.comment])

    def link(self, link: Link) -> None:
        """Append `Closes #issue` to the pull request's body unless a closing keyword is there."""
        body = self._ok(["pr", "view", str(link.pr), "--json", "body", "-q", ".body"])
        if not re.search(CLOSING.format(link.issue), body, re.IGNORECASE):
            self._ok(["pr", "edit", str(link.pr), "--body",
                      f"{body.rstrip()}\n\nCloses #{link.issue}\n"])


# Sessions: a worktree, a headless lfg run in it, its log

WORKTREES = ".claude/worktrees"
STATE = ".dispatch"
GRACE = 10.0  # seconds a session gets to exit after terminate, before kill
PROMPT = ("/compound-engineering:lfg #{issue}\n\n"
          "The pull request body must contain the line `Closes #{issue}`, "
          "so merging it closes the issue.")
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
        log = self.root / STATE / "logs" / f"issue-{issue}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as output:
            process = self.spawn(["claude", "-p", PROMPT.format(issue=issue), *FLAGS],
                                 cwd=worktree, stdin=subprocess.DEVNULL, stdout=output,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        return Running(issue, name, worktree, log, process)

    def reason(self, running: Running) -> str:
        """Why a session ended: its final result's text, else its exit code."""
        lines = running.log.read_text(errors="replace").splitlines() if running.log.exists() else []
        for line in reversed(lines):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "result" and event.get("result"):
                return str(event["result"]).strip()[:2000]
        return f"the session exited with code {running.process.returncode} and no final result"

    def end(self, running: Running) -> None:
        """Terminate a session; kill it when it hasn't exited after the grace period."""
        running.process.terminate()
        try:
            running.process.wait(GRACE)
        except subprocess.TimeoutExpired:
            running.process.kill()
            running.process.wait()

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


class Dispatcher:
    """Applies each poll's actions through GitHub and the sessions; owns the running sessions."""

    def __init__(self, gh: GitHub, sessions: Sessions, slots: int,
                 say: Callable[[str], None] = print) -> None:
        """Up to `slots` sessions; progress lines through `say`."""
        self.gh = gh
        self.sessions = sessions
        self.slots = slots
        self.say = say
        self.running: dict[int, Running] = {}
        self.branches: dict[int, str] = {}  # issues in review: the branch their session pushed

    def start(self) -> None:
        """Create the missing labels; mark the issues left in progress (R11)."""
        self.gh.ensure_labels()
        stranded = [issue for issue, _ in self.gh.issues(IN_PROGRESS)]
        for move in orphans(stranded, self.sessions.worktrees() if stranded else {}):
            self.apply(move)

    def snapshot(self) -> tuple[Snapshot, list[Running]]:
        """Read GitHub: ended sessions' pull requests, issues in review, the ready queue."""
        over = [running for running in self.running.values() if running.process.poll() is not None]
        ended = []
        for running in over:
            prs = self.gh.head(running.branch)
            ended.append(Ended(running.issue, str(running.worktree), str(running.log),
                               "" if prs else self.sessions.reason(running), prs,
                               self.gh.linked(running.issue) if prs else frozenset()))
            if prs:
                self.branches[running.issue] = running.branch
        reviews = []
        for issue, prs in self.gh.issues(IN_REVIEW):
            if not prs and issue.number in self.branches:
                prs = self.gh.head(self.branches[issue.number])
            reviews.append(Review(issue.number, any(self.gh.passing(pr.number) for pr in prs)))
        ready = tuple(issue for issue, _ in self.gh.issues(READY))
        return Snapshot(tuple(ended), tuple(reviews), ready), over

    def tick(self) -> None:
        """One poll: read, decide, apply. A failed read skips the poll; ended sessions wait."""
        try:
            snapshot, over = self.snapshot()
        except (GhError, ValueError, KeyError) as error:
            self.say(f"dispatcher: poll skipped: {error}")
            return
        for running in over:
            del self.running[running.issue]
        for action in tick(snapshot, set(self.running), self.slots):
            self.apply(action)

    def apply(self, action: Action) -> None:
        """One action; a failed `gh` call is reported and the others still run."""
        try:
            match action:
                case Move():
                    self.gh.move(action)
                    self.say(f"dispatcher: #{action.issue} -> {', '.join(action.add)}")
                case Link():
                    self.gh.link(action)
                case Dispatch():
                    self.dispatch(action.issue)
        except GhError as error:
            self.say(f"dispatcher: {action}: {error}")

    def dispatch(self, issue: int) -> None:
        """In progress, then a session; one that cannot start needs attention (R10).

        A failed label swap raises before the session: the issue stays `ready` for the next poll.
        """
        self.gh.move(Move(issue, (READY, NEEDS_ATTENTION), (IN_PROGRESS,)))
        self.say(f"dispatcher: #{issue} -> {IN_PROGRESS}")
        try:
            running = self.sessions.start(issue)
        except (OSError, subprocess.CalledProcessError) as error:
            detail = getattr(error, "stderr", None) or error
            self.apply(Move(issue, (IN_PROGRESS,), (NEEDS_ATTENTION,),
                            f"Dispatcher: the session could not start: {str(detail).strip()}\n\n"
                            "Add `ready` to queue it again."))
            return
        self.running[issue] = running
        self.say(f"dispatcher: #{issue} running in {running.worktree}, log {running.log}")

    def stop(self) -> None:
        """End every session and mark its issue: the dispatcher was stopped."""
        for running in list(self.running.values()):
            self.sessions.end(running)
            del self.running[running.issue]
            self.apply(Move(running.issue, (IN_PROGRESS,), (NEEDS_ATTENTION,),
                            "Dispatcher: the dispatcher was stopped while the session ran.\n\n"
                            f"Worktree: `{running.worktree}`\n\nLog: `{running.log}`\n\n"
                            "Add `ready` to queue it again."))


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
    if lock.exists():
        holder = lock.read_text().strip()
        if holder.isdigit() and alive(int(holder)):
            return False
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(os.getpid()))
    return True


def serve(boss: Dispatcher, every: float) -> None:
    """Poll every `every` seconds until SIGINT or SIGTERM, then stop the sessions."""
    stopping = threading.Event()

    def stop(signum: int, frame: object) -> None:
        stopping.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    boss.start()
    while not stopping.is_set():
        boss.tick()
        stopping.wait(every)
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
