"""tools/dispatcher/dispatcher.py: the author's ready issues become pull requests through lfg sessions."""

from collections.abc import Callable, Iterator
import dataclasses
import json
import os
from pathlib import Path
import signal
import subprocess
from typing import Any

import pytest

import dispatcher
from dispatcher import (IN_PROGRESS, IN_REVIEW, NEEDS_ATTENTION, READY, READY_TO_MERGE, Dispatch,
                        Ended, Issue, Link, Move, PullRequest, Review, Snapshot)

PR = PullRequest(101, "https://github.com/o/r/pull/101")


def ready(number: int, *, blocked: int = 0, also: tuple[str, ...] = ()) -> Issue:
    return Issue(number, frozenset((READY, *also)), blocked)


def ended(issue: int, *, prs: tuple[PullRequest, ...] = (), linked: frozenset[int] = frozenset(),
          reason: str = "lfg stopped: no work source") -> Ended:
    return Ended(issue, f"/repo/.claude/worktrees/issue-{issue}", "/repo/tools/dispatcher/.state/logs/x.log",
                 reason, prs, linked)


# The queue

def test_a_blocked_issue_is_skipped_and_dispatched_once_its_blocker_closes() -> None:
    """AE1: #72 waits on #70; once #70 is gone from the queue and closed, #72 goes."""
    snapshot = Snapshot(ready=(ready(70), ready(72, blocked=1)))
    assert dispatcher.tick(snapshot, set(), 1) == [Dispatch(70)]
    assert dispatcher.tick(Snapshot(ready=(ready(72),)), set(), 1) == [Dispatch(72)]


def test_the_oldest_free_issue_goes_first() -> None:
    """AE2: the oldest is blocked, the second is not."""
    snapshot = Snapshot(ready=(ready(25, blocked=2), ready(69), ready(71)))
    assert dispatcher.tick(snapshot, set(), 1) == [Dispatch(69)]


def test_no_more_sessions_than_slots() -> None:
    """AE3: two running with N 2, a third waits; one ends, one goes."""
    snapshot = Snapshot(ready=(ready(71),))
    assert dispatcher.tick(snapshot, {69, 70}, 2) == []
    assert dispatcher.tick(snapshot, {70}, 2) == [Dispatch(71)]


def test_an_issue_running_or_in_progress_is_not_dispatched_again() -> None:
    snapshot = Snapshot(ready=(ready(69), ready(70, also=(IN_PROGRESS,)), ready(71)))
    assert dispatcher.tick(snapshot, {69}, 3) == [Dispatch(71)]


def test_free_slots_fill_in_order() -> None:
    snapshot = Snapshot(ready=(ready(69), ready(70), ready(71)))
    assert dispatcher.tick(snapshot, set(), 2) == [Dispatch(69), Dispatch(70)]


# A session's end

def test_a_session_that_opened_a_pull_request_goes_in_review() -> None:
    """AE4: in review with the link; the slot frees."""
    move, = dispatcher.judge(ended(74, prs=(PR,), linked=frozenset({101})))
    assert isinstance(move, Move)
    assert (move.issue, move.remove, move.add) == (74, (IN_PROGRESS,), (IN_REVIEW,))
    assert PR.url in (move.comment or "")
    assert dispatcher.tick(Snapshot(ready=(ready(75),)), set(), 1) == [Dispatch(75)]


def test_a_pull_request_not_linked_to_its_issue_gets_the_link() -> None:
    """AE1 relies on merging closing the issue: the dispatcher adds Closes #N."""
    assert Link(101, 74) in dispatcher.judge(ended(74, prs=(PR,)))
    linked = dispatcher.judge(ended(74, prs=(PR,), linked=frozenset({101})))
    assert not [action for action in linked if isinstance(action, Link)]


def test_a_session_without_a_pull_request_needs_attention() -> None:
    """AE5: the reason and the worktree in the comment."""
    move, = dispatcher.judge(ended(74))
    assert isinstance(move, Move)
    assert (move.remove, move.add) == ((IN_PROGRESS,), (NEEDS_ATTENTION,))
    assert "lfg stopped: no work source" in (move.comment or "")
    assert "/repo/.claude/worktrees/issue-74" in (move.comment or "")


# Promotion

def test_an_issue_in_review_whose_checks_pass_is_ready_to_merge() -> None:
    """AE4, later: every required check passes."""
    assert dispatcher.tick(Snapshot(reviews=(Review(74, True),)), set(), 1) == [
        Move(74, (IN_REVIEW,), (READY_TO_MERGE,))]


def test_pending_or_failing_checks_leave_it_in_review() -> None:
    assert dispatcher.tick(Snapshot(reviews=(Review(74, False),)), set(), 1) == []


# Start

def test_an_in_progress_issue_at_start_needs_attention() -> None:
    """AE6: the orphan fails with its worktree; issues in review are not in the input at all."""
    move, = dispatcher.orphans([Issue(74, frozenset({IN_PROGRESS}))],
                             {74: ["/repo/.claude/worktrees/issue-74"]})
    assert (move.issue, move.remove, move.add) == (74, (IN_PROGRESS,), (NEEDS_ATTENTION,))
    assert "/repo/.claude/worktrees/issue-74" in (move.comment or "")


# The gh gateway

class FakeGh:
    """`gh` answering from a script of (argument prefix, exit code, stdout); records every call."""

    def __init__(self, *script: tuple[tuple[str, ...], int, str]) -> None:
        self.script = list(script)
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> tuple[int, str, str]:
        self.calls.append(args)
        for prefix, code, out in self.script:
            if tuple(args[:len(prefix)]) == prefix:
                return code, out, "" if code == 0 else "gh: something broke"
        return 0, "", ""


def nodes(*issues: dict[str, object]) -> str:
    return json.dumps({"data": {"repository": {"issues": {"nodes": list(issues)}}}})


def node(number: int, labels: tuple[str, ...], blocked: int = 0,
         prs: tuple[tuple[int, str], ...] = (), forks: tuple[int, ...] = ()) -> dict[str, object]:
    return {"number": number, "labels": {"nodes": [{"name": name} for name in labels]},
            "issueDependenciesSummary": {"blockedBy": blocked},
            "closedByPullRequestsReferences": {"nodes": [
                {"number": n, "url": f"https://github.com/o/r/pull/{n}", "state": state,
                 "isCrossRepository": n in forks}
                for n, state in prs]}}


def github(*script: tuple[tuple[str, ...], int, str]) -> tuple[dispatcher.GitHub, FakeGh]:
    fake = FakeGh((("api", "user"), 0, "me\n"), *script)
    return dispatcher.GitHub(fake), fake


def test_the_ready_queue_in_creation_order_with_blocked_counts() -> None:
    gh, fake = github((("api", "graphql"), 0, nodes(node(70, ("ready",)),
                                                     node(72, ("ready",), blocked=1))))
    assert [(issue.number, issue.blocked) for issue, _ in gh.issues(READY)] == [(70, 0), (72, 1)]
    query = fake.calls[-1]
    assert "createdBy: $login" in " ".join(query)
    assert "login=me" in query
    assert "label=ready" in query


def test_only_open_pull_requests_linked_to_an_issue_are_kept() -> None:
    gh, _ = github((("api", "graphql"), 0, nodes(
        node(74, ("in review",), prs=((99, "MERGED"), (101, "OPEN"))))))
    (_, prs), = gh.issues(IN_REVIEW)
    assert [pr.number for pr in prs] == [101]


def test_a_forks_pull_request_linked_to_an_issue_is_not_kept() -> None:
    """The repository is public: a fork's PR saying `Closes #N` must not promote the issue."""
    gh, _ = github((("api", "graphql"), 0, nodes(
        node(74, ("in review",), prs=((101, "OPEN"), (102, "OPEN")), forks=(102,)))))
    (_, prs), = gh.issues(IN_REVIEW)
    assert [pr.number for pr in prs] == [101]


def linked_reply(*prs: tuple[int, bool]) -> str:
    return json.dumps({"data": {"repository": {"issue": {"closedByPullRequestsReferences": {
        "nodes": [{"number": n, "isCrossRepository": fork} for n, fork in prs]}}}}})


def test_the_pull_requests_linked_to_an_issue() -> None:
    gh, fake = github((("api", "graphql"), 0, linked_reply((99, False), (101, False))))
    assert gh.linked(74) == frozenset({99, 101})
    assert "number=74" in fake.calls[-1]


def test_a_forks_pull_request_is_not_linked() -> None:
    gh, _ = github((("api", "graphql"), 0, linked_reply((101, False), (102, True))))
    assert gh.linked(74) == frozenset({101})


def test_required_checks_verdicts() -> None:
    for code, verdict in ((0, True), (8, False), (1, False)):
        gh, fake = github((("pr", "checks"), code, ""))
        assert gh.passing(101) is verdict
        assert fake.calls[-1] == ["pr", "checks", "101", "--required"]


def test_only_missing_labels_are_created() -> None:
    gh, fake = github((("label", "list"), 0, json.dumps(
        [{"name": name} for name in (READY, IN_PROGRESS, IN_REVIEW, "bug")])))
    gh.ensure_labels()
    created = [call[2] for call in fake.calls if call[:2] == ["label", "create"]]
    assert created == [READY_TO_MERGE, NEEDS_ATTENTION]


def test_a_dispatch_swaps_labels_in_one_edit() -> None:
    gh, fake = github()
    gh.move(Move(74, (READY, NEEDS_ATTENTION), (IN_PROGRESS,)))
    assert fake.calls == [["issue", "edit", "74", "--remove-label", "ready",
                           "--remove-label", "needs attention", "--add-label", "in progress"]]


def test_a_move_with_a_comment_comments_after_the_swap() -> None:
    gh, fake = github()
    gh.move(Move(74, (IN_PROGRESS,), (IN_REVIEW,), "Dispatcher: hi"))
    assert fake.calls[1] == ["issue", "comment", "74", "--body", "Dispatcher: hi"]


def test_a_pull_request_without_the_closing_line_gets_it_once() -> None:
    """AE1: merging must close the issue."""
    gh, fake = github((("pr", "view"), 0, "Summary of the change\n"))
    gh.link(Link(101, 74))
    assert fake.calls[-1] == ["pr", "edit", "101", "--body",
                              "Summary of the change\n\nCloses #74\n"]
    gh, fake = github((("pr", "view"), 0, "Summary\n\nCloses #74\n"))
    gh.link(Link(101, 74))
    assert not [call for call in fake.calls if call[:2] == ["pr", "edit"]]


def test_the_open_pull_requests_of_a_branch() -> None:
    gh, fake = github((("pr", "list"), 0, json.dumps(
        [{"number": 101, "url": "https://github.com/o/r/pull/101", "isCrossRepository": False}])))
    assert gh.head("issue-74") == (PR,)
    assert fake.calls[-1][:6] == ["pr", "list", "--head", "issue-74", "--state", "open"]


def test_a_forks_branch_of_the_same_name_is_not_the_sessions() -> None:
    """`--head issue-74` matches any fork's `issue-74` too: only this repository's PR counts."""
    gh, fake = github((("pr", "list"), 0, json.dumps(
        [{"number": 102, "url": "https://github.com/o/r/pull/102", "isCrossRepository": True}])))
    assert gh.head("issue-74") == ()
    assert "number,url,isCrossRepository" in fake.calls[-1]


def test_a_failing_gh_call_raises_with_its_stderr() -> None:
    gh, _ = github((("issue", "edit"), 1, ""))
    swap = Move(74, (READY,), (IN_PROGRESS,))
    with pytest.raises(dispatcher.GhError, match="something broke"):
        gh.move(swap)


# The session runner

class FakeGit:
    """`git` with these branches; records every call."""

    def __init__(self, *branches: str, fail: str = "") -> None:
        self.branches = set(branches)
        self.fail = fail
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        if self.fail and args[:2] == self.fail.split():
            raise subprocess.CalledProcessError(128, ["git", *args], stderr="fatal: no space")
        if args[:2] == ["branch", "--list"]:
            return "\n".join(f"  {name}" for name in self.branches if name == args[2])
        return ""


class FakeProcess:
    def __init__(self, *, stubborn: bool = False) -> None:
        self.stubborn = stubborn
        self.signals: list[str] = []
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.signals.append("terminate")

    def kill(self) -> None:
        self.signals.append("kill")
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.stubborn and "kill" not in self.signals:
            raise subprocess.TimeoutExpired("claude", timeout or 0)
        self.returncode = self.returncode if self.returncode is not None else -15
        return self.returncode


class FakeSpawn:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, args: list[str], **options: Any) -> FakeProcess:
        self.calls.append((args, options))
        return FakeProcess()


def sessions(tmp_path: Path, git: FakeGit) -> tuple[dispatcher.Sessions, FakeSpawn]:
    spawn = FakeSpawn()
    return dispatcher.Sessions(tmp_path, git, spawn), spawn


def test_a_session_starts_in_a_new_worktree_from_origin_main(tmp_path: Path) -> None:
    git = FakeGit()
    runner, spawn = sessions(tmp_path, git)
    running = runner.start(74)
    worktree = tmp_path / ".claude/worktrees/issue-74"
    assert git.calls[0] == ["fetch", "origin", "main"]
    assert ["worktree", "add", "-b", "issue-74", str(worktree), "origin/main"] in git.calls
    assert (running.issue, running.branch, running.worktree) == (74, "issue-74", worktree)
    assert running.log == tmp_path / dispatcher.STATE / "logs/issue-74.log"


def test_a_taken_name_gets_a_suffix(tmp_path: Path) -> None:
    runner, _ = sessions(tmp_path, FakeGit("issue-74"))
    assert runner.start(74).branch == "issue-74-2"
    (tmp_path / ".claude/worktrees/issue-75").mkdir(parents=True)
    assert runner.start(75).branch == "issue-75-2"


def test_the_session_runs_lfg_headless_in_its_worktree(tmp_path: Path) -> None:
    runner, spawn = sessions(tmp_path, FakeGit())
    runner.start(74)
    (args, options), = spawn.calls
    assert args[:2] == ["claude", "-p"]
    assert args[2].startswith("/compound-engineering:lfg #74")
    assert "Closes #74" in args[2]
    assert args[3:] == ["--permission-mode", "auto", "--output-format", "stream-json", "--verbose"]
    assert options["cwd"] == tmp_path / ".claude/worktrees/issue-74"
    assert options["start_new_session"] is True


def test_a_failing_worktree_raises(tmp_path: Path) -> None:
    runner, spawn = sessions(tmp_path, FakeGit(fail="worktree add"))
    with pytest.raises(subprocess.CalledProcessError):
        runner.start(74)
    assert spawn.calls == []


def test_the_reason_is_the_final_result_or_the_exit_code(tmp_path: Path) -> None:
    runner, _ = sessions(tmp_path, FakeGit())
    running = runner.start(74)
    process = running.process
    assert isinstance(process, FakeProcess)
    process.returncode = 1
    running.log.write_text("\n".join([
        json.dumps({"type": "assistant", "message": {}}),
        json.dumps({"type": "result", "is_error": False,
                    "result": "Stopped: the plan returned blocked."}),
        "not json"]))
    assert runner.reason(running) == "Stopped: the plan returned blocked."
    running.log.write_text(json.dumps({"type": "assistant"}) + "\n")
    assert runner.reason(running) == "the session exited with code 1 and no final result"


def test_a_new_attempt_never_reports_an_earlier_attempts_result(tmp_path: Path) -> None:
    """The log is per issue and appended: a retry that dies silently has its own reason."""
    runner, _ = sessions(tmp_path, FakeGit())
    first = runner.start(74)
    first.log.write_text(json.dumps({"type": "result", "result": "First attempt: blocked."}) + "\n")
    again = runner.start(74)
    process = again.process
    assert isinstance(process, FakeProcess)
    process.returncode = 1
    with again.log.open("a") as log:
        log.write(json.dumps({"type": "assistant"}) + "\n")
    assert runner.reason(again) == "the session exited with code 1 and no final result"


def test_a_session_that_ignores_terminate_is_killed(tmp_path: Path) -> None:
    runner, _ = sessions(tmp_path, FakeGit())
    running = runner.start(74)
    stubborn = FakeProcess(stubborn=True)
    runner.end([dataclasses.replace(running, process=stubborn)])
    assert stubborn.signals == ["terminate", "kill"]


def test_worktrees_by_issue(tmp_path: Path) -> None:
    git = FakeGit()
    runner, _ = sessions(tmp_path, git)
    listing = "\n".join([f"worktree {tmp_path}", "HEAD abc", "branch refs/heads/main", "",
                         f"worktree {tmp_path}/.claude/worktrees/issue-74", "",
                         f"worktree {tmp_path}/.claude/worktrees/issue-74-2", "",
                         f"worktree {tmp_path}/.claude/worktrees/bridge-x", ""])
    runner.git = lambda args: listing
    assert runner.worktrees() == {74: [f"{tmp_path}/.claude/worktrees/issue-74",
                                       f"{tmp_path}/.claude/worktrees/issue-74-2"]}


# The command

class FakeGitHub:
    """The gateway's interface over fixed answers; records the writes."""

    def __init__(self, issues: dict[str, list[tuple[Issue, tuple[PullRequest, ...]]]] | None = None,
                 *, head: dict[str, tuple[PullRequest, ...]] | None = None,
                 linked: frozenset[int] = frozenset(), passing: bool = False,
                 broken: int | None = None) -> None:
        self.answers = issues or {}
        self.heads = head or {}
        self.linked_prs = linked
        self.checks = passing
        self.broken = broken
        self.flaky: set[str] = set()  # calls that fail once, the next time they are made
        self.writes: list[object] = []

    def _flake(self, call: str) -> None:
        if call in self.flaky:
            self.flaky.discard(call)
            raise dispatcher.GhError(f"gh {call}: HTTP 502")

    def ensure_labels(self) -> None:
        self.writes.append("labels")

    def issues(self, label: str) -> list[tuple[Issue, tuple[PullRequest, ...]]]:
        return self.answers.get(label, [])

    def head(self, branch: str) -> tuple[PullRequest, ...]:
        self._flake("head")
        return self.heads.get(branch, ())

    def linked(self, issue: int) -> frozenset[int]:
        return self.linked_prs

    def passing(self, pr: int) -> bool:
        return self.checks

    def move(self, move: Move) -> None:
        if move.issue == self.broken:
            raise dispatcher.GhError("gh issue: HTTP 502")
        self._flake("move")
        self.writes.append(move)

    def link(self, link: Link) -> None:
        self._flake("link")
        self.writes.append(link)


def moves(gh: FakeGitHub) -> list[tuple[int, tuple[str, ...]]]:
    return [(write.issue, write.add) for write in gh.writes if isinstance(write, Move)]


def test_misuse_prints_the_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert dispatcher.main(["dispatcher.py"]) == 2
    assert "python3 tools/dispatcher/dispatcher.py run" in capsys.readouterr().out


def test_a_second_dispatcher_refuses_to_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    lock = tmp_path / dispatcher.STATE / "lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(str(os.getpid()))
    monkeypatch.setattr(dispatcher, "ROOT", tmp_path)
    monkeypatch.setattr(dispatcher, "GitHub", lambda: pytest.fail("no gh call when refusing"))
    assert dispatcher.main(["dispatcher.py", "run"]) == 1
    assert str(os.getpid()) in capsys.readouterr().out


def test_a_dead_dispatchers_lock_is_taken_over(tmp_path: Path) -> None:
    gone = subprocess.Popen(["true"])
    gone.wait()
    lock = tmp_path / "lock"
    lock.write_text(str(gone.pid))
    assert dispatcher.take(lock)
    assert lock.read_text() == str(os.getpid())
    assert not dispatcher.take(lock)


def test_start_marks_the_orphans_before_the_first_poll(tmp_path: Path) -> None:
    """AE6: the orphan gets its worktree in the comment, before the first poll."""
    gh = FakeGitHub({IN_PROGRESS: [(Issue(74, frozenset({IN_PROGRESS})), ())]})
    runner, _ = sessions(tmp_path, FakeGit())
    runner.git = lambda args: f"worktree {tmp_path}/.claude/worktrees/issue-74\n"
    dispatcher.Dispatcher(gh, runner, 2, say=lambda line: None).start()
    assert gh.writes[0] == "labels"
    move = gh.writes[1]
    assert isinstance(move, Move)
    assert move.add == (NEEDS_ATTENTION,)
    assert f"{tmp_path}/.claude/worktrees/issue-74" in (move.comment or "")


def test_a_poll_dispatches_then_judges_the_ended_session(tmp_path: Path) -> None:
    """AE4 end to end: dispatched, PR opened without the link, in review, then ready to merge."""
    gh = FakeGitHub({READY: [(ready(74), ())]}, head={"issue-74": (PR,)})
    runner, spawn = sessions(tmp_path, FakeGit())
    lines: list[str] = []
    boss = dispatcher.Dispatcher(gh, runner, 1, say=lines.append)
    boss.poll()
    assert moves(gh) == [(74, (IN_PROGRESS,))]
    assert len(spawn.calls) == 1
    process = boss.running[74].process
    assert isinstance(process, FakeProcess)
    process.returncode = 0
    gh.answers = {IN_REVIEW: [(Issue(74, frozenset({IN_REVIEW})), ())]}
    gh.checks = True
    boss.poll()
    assert moves(gh)[1:] == [(74, (IN_REVIEW,)), (74, (READY_TO_MERGE,))]
    assert Link(101, 74) in gh.writes
    assert boss.running == {}
    assert any("#74" in line and IN_REVIEW in line for line in lines)


def test_a_session_that_cannot_start_needs_attention(tmp_path: Path) -> None:
    """AE5: a failing worktree after the swap; the slot stays free for the next issue."""
    gh = FakeGitHub({READY: [(ready(74), ())]})
    runner, _ = sessions(tmp_path, FakeGit(fail="worktree add"))
    boss = dispatcher.Dispatcher(gh, runner, 1, say=lambda line: None)
    boss.poll()
    assert moves(gh) == [(74, (IN_PROGRESS,)), (74, (NEEDS_ATTENTION,))]
    assert "no space" in (gh.writes[-1].comment or "")  # type: ignore[union-attr]
    assert boss.running == {}


def test_stopping_ends_the_sessions_and_marks_their_issues(tmp_path: Path) -> None:
    gh = FakeGitHub({READY: [(ready(74), ())]})
    runner, _ = sessions(tmp_path, FakeGit())
    boss = dispatcher.Dispatcher(gh, runner, 1, say=lambda line: None)
    boss.poll()
    process = boss.running[74].process
    assert isinstance(process, FakeProcess)
    boss.stop()
    assert process.signals == ["terminate"]
    move = gh.writes[-1]
    assert isinstance(move, Move)
    assert move.add == (NEEDS_ATTENTION,)
    assert "stopped" in (move.comment or "")
    assert boss.running == {}


def test_a_failing_label_swap_does_not_stop_the_poll(tmp_path: Path) -> None:
    gh = FakeGitHub({READY: [(ready(73), ()), (ready(74), ())]}, broken=73)
    runner, spawn = sessions(tmp_path, FakeGit())
    lines: list[str] = []
    boss = dispatcher.Dispatcher(gh, runner, 2, say=lines.append)
    boss.poll()
    assert moves(gh) == [(74, (IN_PROGRESS,))]
    assert len(spawn.calls) == 1
    assert any("HTTP 502" in line for line in lines)


def ended_session(tmp_path: Path, gh: FakeGitHub) -> dispatcher.Dispatcher:
    """A dispatcher whose session for #74 ran and exited, not judged yet."""
    runner, _ = sessions(tmp_path, FakeGit())
    boss = dispatcher.Dispatcher(gh, runner, 1, say=lambda line: None)
    gh.answers = {READY: [(ready(74), ())]}
    boss.poll()
    gh.answers = {}
    process = boss.running[74].process
    assert isinstance(process, FakeProcess)
    process.returncode = 0
    return boss


def test_a_failed_move_after_a_session_ends_is_retried_at_the_next_poll(tmp_path: Path) -> None:
    gh = FakeGitHub(head={"issue-74": (PR,)})
    boss = ended_session(tmp_path, gh)
    gh.flaky = {"move"}
    boss.poll()
    assert (74, (IN_REVIEW,)) not in moves(gh)
    assert boss.running == {}
    boss.poll()
    assert moves(gh).count((74, (IN_REVIEW,))) == 1
    assert [write.comment for write in gh.writes  # type: ignore[union-attr]
            if isinstance(write, Move) and write.add == (IN_REVIEW,)] == [
        f"Dispatcher: pull request {PR.url} is open."]
    boss.poll()
    assert moves(gh).count((74, (IN_REVIEW,))) == 1


def test_a_failed_link_after_a_session_ends_is_retried_at_the_next_poll(tmp_path: Path) -> None:
    gh = FakeGitHub(head={"issue-74": (PR,)})
    boss = ended_session(tmp_path, gh)
    gh.flaky = {"link"}
    boss.poll()
    assert Link(101, 74) not in gh.writes
    assert (74, (IN_REVIEW,)) in moves(gh)
    boss.poll()
    assert gh.writes.count(Link(101, 74)) == 1
    boss.poll()
    assert gh.writes.count(Link(101, 74)) == 1


def test_an_ended_session_github_cannot_read_waits_for_the_next_poll(tmp_path: Path) -> None:
    gh = FakeGitHub(head={"issue-74": (PR,)})
    boss = ended_session(tmp_path, gh)
    gh.flaky = {"head"}
    boss.poll()
    assert 74 in boss.running
    assert moves(gh) == [(74, (IN_PROGRESS,))]
    boss.poll()
    assert boss.running == {}
    assert (74, (IN_REVIEW,)) in moves(gh)


def two_sessions(tmp_path: Path, gh: FakeGitHub) -> tuple[dispatcher.Dispatcher, FakeProcess,
                                                          FakeProcess]:
    """A dispatcher whose session for #74 exited with code 0 while #75's still runs."""
    runner, _ = sessions(tmp_path, FakeGit())
    boss = dispatcher.Dispatcher(gh, runner, 2, say=lambda line: None)
    gh.answers = {READY: [(ready(74), ()), (ready(75), ())]}
    boss.poll()
    gh.answers = {}
    done, live = boss.running[74].process, boss.running[75].process
    assert isinstance(done, FakeProcess)
    assert isinstance(live, FakeProcess)
    done.returncode = 0
    return boss, done, live


def test_stopping_judges_a_session_that_already_ended(tmp_path: Path) -> None:
    """KTD3 at stop: #74 opened its PR and exited before Ctrl-C, so it is in review."""
    gh = FakeGitHub(head={"issue-74": (PR,)})
    boss, done, live = two_sessions(tmp_path, gh)
    boss.stop()
    assert done.signals == []
    assert live.signals == ["terminate"]
    assert moves(gh)[2:] == [(74, (IN_REVIEW,)), (75, (NEEDS_ATTENTION,))]
    assert Link(101, 74) in gh.writes
    move = gh.writes[-1]
    assert isinstance(move, Move)
    assert "stopped while the session ran" in (move.comment or "")
    assert boss.running == {}


def test_stopping_when_github_cannot_read_an_ended_session(tmp_path: Path) -> None:
    gh = FakeGitHub(head={"issue-74": (PR,)})
    boss, _, _ = two_sessions(tmp_path, gh)
    gh.flaky = {"head"}
    boss.stop()
    assert moves(gh)[2:] == [(74, (NEEDS_ATTENTION,)), (75, (NEEDS_ATTENTION,))]
    move = gh.writes[2]
    assert isinstance(move, Move)
    assert "HTTP 502" in (move.comment or "")


# The loop and the lock

class Boss:
    """A dispatcher standing in for serve(): its poll runs `polled`; records the calls."""

    def __init__(self, polled: Callable[[], None]) -> None:
        self.polled = polled
        self.calls: list[str] = []

    def say(self, line: str) -> None:
        self.calls.append(line)

    def start(self) -> None:
        self.calls.append("start")

    def poll(self) -> None:
        self.calls.append("poll")
        self.polled()

    def stop(self) -> None:
        self.calls.append("stop")


@pytest.fixture
def handlers() -> Iterator[None]:
    """serve() installs SIGINT and SIGTERM handlers: put the test runner's back."""
    saved = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
    yield
    for signum, handler in saved.items():
        signal.signal(signum, handler)


@pytest.mark.usefixtures("handlers")
def test_a_signal_ends_the_loop_and_stops_the_sessions() -> None:
    """KTD9: Ctrl-C during a poll ends the loop, then the sessions."""
    boss = Boss(lambda: signal.raise_signal(signal.SIGINT))
    dispatcher.serve(boss, 0)  # type: ignore[arg-type]
    assert boss.calls == ["start", "poll", "dispatcher: stopping", "stop"]


@pytest.mark.usefixtures("handlers")
def test_an_unexpected_error_still_stops_the_sessions() -> None:
    """No session is left running detached when the dispatcher dies of a bug."""
    def broken() -> None:
        raise RuntimeError("a bug")

    boss = Boss(broken)
    with pytest.raises(RuntimeError, match="a bug"):
        dispatcher.serve(boss, 0)  # type: ignore[arg-type]
    assert boss.calls[-1] == "stop"
    assert boss.calls.count("stop") == 1


def command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
            serve: Callable[[object, float], None]) -> Path:
    """main() over trivial gateways and this serve(): the lock it would take."""
    monkeypatch.setattr(dispatcher, "ROOT", tmp_path)
    monkeypatch.setattr(dispatcher, "GitHub", lambda: object())
    monkeypatch.setattr(dispatcher, "Sessions", lambda root: object())
    monkeypatch.setattr(dispatcher, "serve", serve)
    return tmp_path / dispatcher.STATE / "lock"


def test_the_lock_is_held_while_serving_and_released_after(tmp_path: Path,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    held: list[bool] = []
    lock = command(tmp_path, monkeypatch, lambda boss, every: held.append(lock.exists()))
    assert dispatcher.main(["dispatcher.py", "run", "--every", "0"]) == 0
    assert held == [True]
    assert not lock.exists()


def test_the_lock_is_released_when_serving_fails(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    def serve(boss: object, every: float) -> None:
        raise RuntimeError("a bug")

    lock = command(tmp_path, monkeypatch, serve)
    with pytest.raises(RuntimeError, match="a bug"):
        dispatcher.main(["dispatcher.py", "run", "--every", "0"])
    assert not lock.exists()
