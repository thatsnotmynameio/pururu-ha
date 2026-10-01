"""tools/dispatcher/dispatcher.py: the author's ready issues become pull requests."""

from collections.abc import Callable, Iterator
import dataclasses
from datetime import datetime
import json
import os
from pathlib import Path
import re
import signal
import subprocess
from typing import Any

import pytest

import dispatcher
from dispatcher import (IN_PROGRESS, IN_REVIEW, NEEDS_ATTENTION, PAUSED, READY, READY_TO_MERGE,
                        Dispatch, Ended, Hold, Issue, Link, Marker, Move, PullRequest, Resume,
                        Review, Snapshot)

PR = PullRequest(101, "https://github.com/o/r/pull/101")
SESSION = "3f2a9c1e-8b4d-4e6f-9a0b-1c2d3e4f5a6b"


def at(hour: int, minute: int = 0, second: int = 0) -> float:
    """This machine's local wall clock on the day of the examples, in epoch seconds."""
    return datetime(2026, 10, 1, hour, minute, second).timestamp()


def limit(issue: int, reset: float | None = at(20, 30), session: str = SESSION) -> Marker:
    return Marker(session, f"issue-{issue}", None if reset is None else int(reset))


def paused(number: int, *, blocked: int = 0, also: tuple[str, ...] = ()) -> Issue:
    return Issue(number, frozenset((PAUSED, *also)), blocked)


def ready(number: int, *, blocked: int = 0, also: tuple[str, ...] = ()) -> Issue:
    return Issue(number, frozenset((READY, *also)), blocked)


def ended(issue: int, *, prs: tuple[PullRequest, ...] = (), linked: frozenset[int] = frozenset(),
          reason: str = "lfg stopped: no work source", limit: Marker | None = None,
          resumed: Marker | None = None) -> Ended:
    return Ended(issue, f"/repo/.claude/worktrees/issue-{issue}", "/repo/tools/dispatcher/.state/logs/x.log",
                 reason, prs, linked, limit, resumed)


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


# The usage limit

def test_a_session_stopped_by_the_limit_is_paused_with_its_marker() -> None:
    """AE1: #70 stops at 15:10 with `resets 8:30pm`: paused, the comment first, naming 20:30."""
    reset = int(at(20, 30))
    move, = dispatcher.judge(ended(70, limit=limit(70)))
    assert isinstance(move, Move)
    assert (move.issue, move.remove, move.add, move.comment_first) == (
        70, (IN_PROGRESS,), (PAUSED,), True)
    comment = move.comment or ""
    assert "usage limit" in comment
    assert "20:30" in comment
    assert SESSION in comment
    assert "/repo/.claude/worktrees/issue-70" in comment
    assert "/repo/tools/dispatcher/.state/logs/x.log" in comment
    assert comment.splitlines()[-1] == (
        '<!-- dispatcher-pause {"session": "3f2a9c1e-8b4d-4e6f-9a0b-1c2d3e4f5a6b", '
        f'"branch": "issue-70", "reset": {reset}}} -->')


def test_a_limit_with_no_reset_says_it_is_tried_again_at_the_next_poll() -> None:
    """R5: no reset in the message: the comment says so, the marker's reset is null."""
    move, = dispatcher.judge(ended(70, limit=limit(70, reset=None)))
    assert isinstance(move, Move)
    assert move.add == (PAUSED,)
    comment = move.comment or ""
    assert "next poll" in comment
    assert comment.splitlines()[-1].endswith('"branch": "issue-70", "reset": null} -->')


def test_a_limit_after_the_pull_request_is_open_is_in_review() -> None:
    move, = dispatcher.judge(ended(70, prs=(PR,), linked=frozenset({101}), limit=limit(70)))
    assert isinstance(move, Move)
    assert move.add == (IN_REVIEW,)


def test_a_resumed_session_that_opens_its_pull_request_is_in_review() -> None:
    """AE3: #70 resumed, then opened its pull request and ended."""
    move, = dispatcher.judge(ended(70, prs=(PR,), linked=frozenset({101}), resumed=limit(70)))
    assert isinstance(move, Move)
    assert (move.remove, move.add) == ((IN_PROGRESS,), (IN_REVIEW,))


def test_a_resumed_session_paused_again_comments_only_on_news() -> None:
    """KTD5: a new reset is news; the same session with the same reset is not."""
    unknown = limit(70, reset=None)
    news, = dispatcher.judge(ended(70, limit=limit(70), resumed=unknown))
    assert isinstance(news, Move)
    assert news.add == (PAUSED,)
    assert "20:30" in (news.comment or "")
    same, = dispatcher.judge(ended(70, limit=limit(70, reset=None), resumed=unknown))
    assert same == Move(70, (IN_PROGRESS,), (PAUSED,))


def test_needs_attention_removes_the_label_it_is_given() -> None:
    """R9: a resume that cannot start leaves `paused`."""
    move = dispatcher.needs_attention(70, "the resume could not start.", remove=PAUSED)
    assert (move.remove, move.add) == ((PAUSED,), (NEEDS_ATTENTION,))


def test_no_session_starts_while_the_limit_holds() -> None:
    """AE1: a free slot and a ready #74, but the hold runs to 20:31; the promotion still goes."""
    snapshot = Snapshot(reviews=(Review(72, True),), ready=(ready(74),))
    assert dispatcher.tick(snapshot, set(), 2, at(15, 10), Hold(at(20, 31))) == [
        Move(72, (IN_REVIEW,), (READY_TO_MERGE,))]


def test_the_hold_ends_one_second_after_its_until() -> None:
    snapshot = Snapshot(ready=(ready(74),))
    hold = Hold(at(20, 31))
    assert dispatcher.tick(snapshot, set(), 1, at(20, 31), hold) == []
    assert dispatcher.tick(snapshot, set(), 1, at(20, 31, 1), hold) == [Dispatch(74)]


def test_paused_issues_resume_before_ready_ones() -> None:
    """AE2: #70 and #72 resume, #72's blocker notwithstanding; #74 waits for a slot."""
    snapshot = Snapshot(ready=(ready(74),), paused=(paused(70), paused(72, blocked=1)))
    assert dispatcher.tick(snapshot, set(), 2, at(20, 35), Hold()) == [Resume(70), Resume(72)]
    assert dispatcher.tick(snapshot, set(), 3, at(20, 35), Hold()) == [
        Resume(70), Resume(72), Dispatch(74)]
    assert dispatcher.tick(snapshot, {70}, 3, at(20, 35), Hold()) == [Resume(72), Dispatch(74)]
    assert dispatcher.tick(snapshot, {70}, 2, at(20, 35), Hold()) == [Resume(72)]


def test_a_probe_starts_one_session_a_paused_one_first() -> None:
    """AE6, KTD4: the tick after an unknown reset starts one session."""
    probe = Hold(at(15, 10), probe=True)
    both = Snapshot(ready=(ready(74),), paused=(paused(70), paused(72)))
    assert dispatcher.tick(both, set(), 2, at(15, 15), probe) == [Resume(70)]
    queue = Snapshot(ready=(ready(74), ready(75)))
    assert dispatcher.tick(queue, set(), 2, at(15, 15), probe) == [Dispatch(74)]


def test_an_issue_whose_paused_label_was_removed_is_not_resumed() -> None:
    """AE7: after the reset, #70 is no longer among the paused issues."""
    assert dispatcher.tick(Snapshot(), set(), 2, at(21), Hold()) == []


def test_a_paused_issue_marked_ready_is_resumed_never_dispatched() -> None:
    """KTD6: `ready` on a paused issue never starts a fresh worktree beside its conversation."""
    both = paused(70, also=(READY,))
    assert dispatcher.pick([both], set(), 1) == []
    assert dispatcher.tick(Snapshot(ready=(both,), paused=(both,)), set(), 2, at(21), Hold()) == [
        Resume(70)]


def test_a_known_reset_holds_until_a_minute_after_it_and_never_shortens() -> None:
    """KTD2: the later reset wins."""
    hold = Hold().extend(int(at(20, 30)), at(15, 10))
    assert hold == Hold(at(20, 31))
    assert hold.extend(int(at(19)), at(15, 20)) == Hold(at(20, 31))
    assert hold.extend(int(at(21)), at(15, 20)) == Hold(at(21, 1))


def test_an_unknown_reset_probes_unless_a_known_one_holds_longer() -> None:
    """KTD4: a known future hold is kept as it is; none becomes a probe at `now`."""
    assert Hold(at(20, 31)).extend(None, at(15, 10)) == Hold(at(20, 31))
    assert Hold().extend(None, at(15, 10)) == Hold(at(15, 10), probe=True)


def test_the_hold_at_start_comes_from_the_paused_markers() -> None:
    """AE4, KTD8: rebuilt from GitHub alone."""
    markers = [limit(70, reset=at(20, 30)), limit(72, reset=at(21))]
    assert dispatcher.restore(markers, at(18)) == Hold(at(21, 1))
    assert dispatcher.restore([limit(70, reset=at(20, 30)), limit(72, reset=at(20, 45))],
                              at(21)) == Hold()
    assert dispatcher.restore([limit(70, reset=None)], at(18)) == Hold(at(18), probe=True)
    assert dispatcher.restore([], at(18)) == Hold()


def test_an_unknown_reset_probes_whatever_order_a_past_reset_comes_in() -> None:
    """KTD4, KTD8: a reset already past never cancels the probe an unknown reset asks for."""
    unknown, past = limit(70, reset=None), limit(72, reset=at(17))
    assert dispatcher.restore([unknown, past], at(18)) == Hold(at(18), probe=True)
    assert dispatcher.restore([past, unknown], at(18)) == Hold(at(18), probe=True)


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
    assert created == [READY_TO_MERGE, NEEDS_ATTENTION, PAUSED]


def test_the_paused_label_is_created_when_missing() -> None:
    """R13: the repository has every label but `paused`."""
    gh, fake = github((("label", "list"), 0, json.dumps(
        [{"name": name} for name in (READY, IN_PROGRESS, IN_REVIEW, READY_TO_MERGE,
                                     NEEDS_ATTENTION)])))
    gh.ensure_labels()
    assert [call for call in fake.calls if call[:2] == ["label", "create"]] == [
        ["label", "create", "paused", "--color", "c5def5", "--description",
         "The session hit the usage limit; it resumes when the limit is back"]]


def test_a_dispatch_swaps_labels_in_one_edit() -> None:
    gh, fake = github()
    gh.move(Move(74, (READY, NEEDS_ATTENTION), (IN_PROGRESS,)))
    assert fake.calls == [["issue", "edit", "74", "--remove-label", "ready",
                           "--remove-label", "needs attention", "--add-label", "in progress"]]


def test_a_move_with_a_comment_comments_after_the_swap() -> None:
    gh, fake = github()
    gh.move(Move(74, (IN_PROGRESS,), (IN_REVIEW,), "Dispatcher: hi"))
    assert fake.calls[1] == ["issue", "comment", "74", "--body", "Dispatcher: hi"]


def test_a_pause_comments_before_the_swap() -> None:
    """KTD3: `paused` never exists without its marker."""
    gh, fake = github()
    gh.move(Move(70, (IN_PROGRESS,), (PAUSED,), "Dispatcher: paused", comment_first=True))
    assert fake.calls == [["issue", "comment", "70", "--body", "Dispatcher: paused"],
                          ["issue", "edit", "70", "--remove-label", "in progress",
                           "--add-label", "paused"]]


OTHER = "9d8c7b6a-5f4e-4d3c-8b2a-1f0e9d8c7b6a"


def comment(login: str, body: str) -> dict[str, object]:
    return {"author": {"login": login}, "body": body, "createdAt": "2026-10-01T15:10:00Z"}


def pause_comment(login: str, session: str, branch: str, reset: int | None) -> dict[str, object]:
    record = json.dumps({"session": session, "branch": branch, "reset": reset})
    return comment(login, "Dispatcher: the Claude usage limit stopped the session.\n\n"
                          f"<!-- dispatcher-pause {record} -->")


def comments_reply(*comments: dict[str, object]) -> tuple[tuple[str, ...], int, str]:
    return ("issue", "view"), 0, json.dumps({"comments": list(comments)})


def test_the_paused_issues_marker_is_the_users_valid_one() -> None:
    """KTD3: a stranger's marker, a session that is no UUID and another issue's branch don't count."""
    gh, fake = github(comments_reply(
        pause_comment("stranger", OTHER, "issue-70", 1759350600),
        pause_comment("me", "--dangerously-skip-permissions", "issue-70", 1759350600),
        pause_comment("me", OTHER, "issue-71", 1759350600),
        pause_comment("me", SESSION, "issue-70-2", 1759350600)))
    assert gh.marker(70) == Marker(SESSION, "issue-70-2", 1759350600)
    assert fake.calls[-1] == ["issue", "view", "70", "--json", "comments"]


def test_a_paused_issue_without_the_users_valid_marker_has_none() -> None:
    gh, _ = github(comments_reply(
        pause_comment("stranger", OTHER, "issue-70", 1759350600),
        pause_comment("me", "--dangerously-skip-permissions", "issue-70", 1759350600),
        pause_comment("me", OTHER, "issue-71", 1759350600),
        comment("me", "Looking into it.")))
    assert gh.marker(70) is None


def test_the_newest_marker_wins() -> None:
    """A retry after a failed swap repeats the comment; a re-pause records a new one."""
    gh, _ = github(comments_reply(pause_comment("me", OTHER, "issue-70", 1759350600),
                                  pause_comment("me", SESSION, "issue-70", None)))
    assert gh.marker(70) == Marker(SESSION, "issue-70", None)


def test_a_marker_round_trips_through_its_line() -> None:
    marker = Marker(SESSION, "issue-70", None)
    body = f"Dispatcher: the Claude usage limit stopped the session.\n\n{marker.line()}"
    assert len(marker.line().splitlines()) == 1
    assert dispatcher.marker_of(body, 70) == marker
    assert dispatcher.marker_of("Dispatcher: pull request is open.", 70) is None


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
    runner, _ = sessions(tmp_path, git)
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
    assert runner.ending(running)[0] == "Stopped: the plan returned blocked."
    running.log.write_text(json.dumps({"type": "assistant"}) + "\n")
    assert runner.ending(running)[0] == "the session exited with code 1 and no final result"


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
    assert runner.ending(again)[0] == "the session exited with code 1 and no final result"


def event(kind: str, session: str = SESSION, **fields: object) -> str:
    return json.dumps({"type": kind, "session_id": session, **fields})


def rejected(resets: int = 1759350600, session: str = SESSION) -> str:
    return event("rate_limit_event", session, rate_limit_info={
        "status": "rejected", "resetsAt": resets, "rateLimitType": "five_hour"})


def result(text: str, *, error: bool = True, session: str = SESSION) -> str:
    return event("result", session, subtype="success", is_error=error, result=text)


INIT = event("system", subtype="init")
QUOTED = event("user", message={"role": "user", "content": [{
    "type": "tool_result",
    "content": "You've hit your session limit · resets 8:30pm (America/Sao_Paulo)"}]})


def slice_of(tmp_path: Path, *lines: str, before: tuple[str, ...] = ()) -> dispatcher.Running:
    """#70's session whose part of the log is `lines`, after an earlier attempt's `before`."""
    log = tmp_path / dispatcher.STATE / "logs/issue-70.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    earlier = "".join(line + "\n" for line in before)
    log.write_text(earlier + "".join(line + "\n" for line in lines))
    process = FakeProcess()
    process.returncode = 1
    return dispatcher.Running(70, "issue-70", tmp_path / ".claude/worktrees/issue-70", log,
                              process, len(earlier.encode()))


def test_a_rejected_limit_with_an_error_result_is_a_limit_ending(tmp_path: Path) -> None:
    """AE1: the session, the branch and resetsAt from the log; with no result at all as well."""
    runner, _ = sessions(tmp_path, FakeGit())
    assert runner.ending(slice_of(tmp_path, INIT, rejected(), result("API Error")))[1] == Marker(
        SESSION, "issue-70", 1759350600)
    assert runner.ending(slice_of(tmp_path, INIT, rejected()))[1] == Marker(
        SESSION, "issue-70", 1759350600)


def test_a_rejected_limit_with_a_successful_result_is_no_limit_ending(tmp_path: Path) -> None:
    """KTD1: extra usage may have covered it."""
    runner, _ = sessions(tmp_path, FakeGit())
    assert runner.ending(slice_of(tmp_path, INIT, rejected(), result("Done.", error=False)))[1] is None


def test_a_tool_output_quoting_the_limit_is_no_limit_ending(tmp_path: Path) -> None:
    """KTD1: only top-level events count, never the text inside them."""
    runner, _ = sessions(tmp_path, FakeGit())
    assert runner.ending(slice_of(tmp_path, INIT, QUOTED, result("Stopped: blocked")))[1] is None


@pytest.mark.parametrize("text", [
    "You've hit your session limit · resets 8:30pm (America/Sao_Paulo)",
    "Claude AI usage limit reached|1759350600"])
def test_a_result_naming_the_limit_is_a_limit_ending_with_an_unknown_reset(
        tmp_path: Path, text: str) -> None:
    """R5: no rejected event, so no reset."""
    runner, _ = sessions(tmp_path, FakeGit())
    assert runner.ending(slice_of(tmp_path, INIT, QUOTED, result(text)))[1] == Marker(
        SESSION, "issue-70", None)


def test_an_earlier_attempts_limit_is_not_this_sessions(tmp_path: Path) -> None:
    runner, _ = sessions(tmp_path, FakeGit())
    running = slice_of(tmp_path, INIT, result("Stopped: blocked"),
                       before=(INIT, rejected(), result("API Error")))
    assert runner.ending(running)[1] is None


def test_the_latest_session_id_is_the_markers(tmp_path: Path) -> None:
    """AE3: a resume may fork the session ID; a later pause records the new one."""
    runner, _ = sessions(tmp_path, FakeGit())
    running = slice_of(tmp_path, INIT, event("assistant", OTHER, message={}),
                       rejected(session=OTHER), result("API Error", session=OTHER))
    assert runner.ending(running)[1] == Marker(OTHER, "issue-70", 1759350600)


def test_an_empty_slice_is_no_limit_ending(tmp_path: Path) -> None:
    """The process exited before any output: judged as today."""
    runner, _ = sessions(tmp_path, FakeGit())
    running = slice_of(tmp_path, before=(INIT, rejected(), result("API Error")))
    assert runner.ending(running)[1] is None
    assert runner.ending(running)[0] == "the session exited with code 1 and no final result"


# The session's progress

def marks(*given: str) -> tuple[str, ...]:
    """These marks for the first stages, the others pending."""
    return (*given, *("pending",) * (len(dispatcher.STAGES) - len(given)))


def skill(name: str, parent: str | None = None) -> dict[str, Any]:
    """An assistant event calling this lfg skill, from a sub-agent when `parent` is set."""
    return {"type": "assistant", "parent_tool_use_id": parent, "session_id": SESSION,
            "message": {"role": "assistant", "content": [{
                "type": "tool_use", "id": "toolu_01", "name": "Skill",
                "input": {"skill": f"compound-engineering:{name}", "args": "mode:pipeline"}}]}}


def says(text: str, parent: str | None = None) -> dict[str, Any]:
    """An assistant event narrating `text`, from a sub-agent when `parent` is set."""
    return {"type": "assistant", "parent_tool_use_id": parent, "session_id": SESSION,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


AE2_SENTENCE = "U1 committed (9073eb3): 1684 tests pass. Dispatching U2, the grammar change."


def test_the_furthest_stage_entered_is_current_and_the_last_text_the_latest() -> None:
    """AE2: plan, doc review, work: the shape of a recorded lfg log."""
    events = [skill("ce-plan"), says("Planning #74."), skill("ce-doc-review"), skill("ce-work"),
              says(AE2_SENTENCE)]
    assert dispatcher.progress_of(events, marks()) == dispatcher.Progress(
        marks("done", "done", "current"), AE2_SENTENCE)


def test_a_route_without_a_plan_skips_it() -> None:
    """AE3: lfg's bug route starts at ce-debug."""
    assert dispatcher.progress_of([skill("ce-debug")], marks()).marks == marks(
        "skipped", "skipped", "current")


def test_a_sub_agents_skills_and_words_move_nothing() -> None:
    events = [skill("ce-plan"), says("Planning #74."), skill("ce-work", parent="toolu_02"),
              says("A sub-agent's report.", parent="toolu_02")]
    assert dispatcher.progress_of(events, marks()) == dispatcher.Progress(marks("current"),
                                                                          "Planning #74.")


def test_unmapped_skills_move_nothing() -> None:
    events = [skill("ce-work"), skill("ce-compound"), skill("ce-noslop")]
    assert dispatcher.progress_of(events, marks()).marks == marks("skipped", "skipped", "current")


def test_the_checklist_never_moves_back() -> None:
    """A plan called after the work is done as entered; the work stays current."""
    events = [skill("ce-work"), skill("ce-plan")]
    assert dispatcher.progress_of(events, marks()).marks == marks("done", "skipped", "current")


def test_before_any_lfg_skill_the_plan_is_current_with_no_sentence() -> None:
    assert dispatcher.progress_of([], marks()) == dispatcher.Progress(marks("current"), None)
    assert dispatcher.progress_of([json.loads(INIT), skill("ce-noslop")], marks()) == (
        dispatcher.Progress(marks("current"), None))


def test_a_resumed_session_continues_from_its_paused_stage() -> None:
    """AE7: paused in implementation; the resume calls ce-code-review."""
    start = marks("done", "done", "paused")
    assert dispatcher.progress_of([], start).marks == marks("done", "done", "current")
    assert dispatcher.progress_of([skill("ce-code-review")], start).marks == marks(
        "done", "done", "done", "current")


def test_the_latest_sentence_is_one_line_of_at_most_200_characters() -> None:
    """KTD4: whitespace collapses; a longer text is cut to 200 characters with an ellipsis."""
    long = "Step one done.\n\n  Now step two:\t" + "x" * 300
    latest = dispatcher.progress_of([says(long)], marks()).latest
    assert latest == ("Step one done. Now step two: " + "x" * 300)[:199] + "…"
    assert len(latest) == 200
    assert dispatcher.progress_of([says("y" * 200)], marks()).latest == "y" * 200


def test_a_missing_log_gives_the_starting_marks_unchanged(tmp_path: Path) -> None:
    runner, _ = sessions(tmp_path, FakeGit())
    running = dispatcher.Running(70, "issue-70", tmp_path / ".claude/worktrees/issue-70",
                                 tmp_path / "missing.log", FakeProcess())
    start = marks("done", "done", "current")
    assert runner.progress(running, start) == dispatcher.Progress(start, None)


def test_a_running_sessions_progress_is_its_own_part_of_the_log(tmp_path: Path) -> None:
    """An earlier attempt's skills and words, before `since`, are not this session's."""
    runner, _ = sessions(tmp_path, FakeGit())
    running = slice_of(tmp_path, INIT, json.dumps(skill("ce-plan")),
                       before=(INIT, json.dumps(skill("ce-work")), json.dumps(says("Earlier."))))
    assert runner.progress(running, marks()) == dispatcher.Progress(marks("current"), None)


def test_the_ending_reads_the_progress_with_the_reason_and_the_limit(tmp_path: Path) -> None:
    """One read; the progress starts from the marks the resume seeded."""
    runner, _ = sessions(tmp_path, FakeGit())
    running = dataclasses.replace(
        slice_of(tmp_path, INIT, json.dumps(skill("ce-code-review")),
                 json.dumps(says("Reviewing.")), rejected(), result("API Error")),
        start_marks=marks("done", "done", "paused"))
    assert runner.ending(running) == ("API Error", Marker(SESSION, "issue-70", 1759350600),
                                      dispatcher.Progress(marks("done", "done", "done", "current"),
                                                          "Reviewing."))


def test_a_resume_continues_the_conversation_headless(tmp_path: Path) -> None:
    """KTD7: the same flags as a dispatch, the limit back in the prompt."""
    (tmp_path / ".claude/worktrees/issue-70").mkdir(parents=True)
    runner, spawn = sessions(tmp_path, FakeGit())
    runner.resume(70, Marker(SESSION, "issue-70", 1759350600))
    (args, _), = spawn.calls
    assert args[:4] == ["claude", "-p", "--resume", SESSION]
    assert args[5:] == ["--permission-mode", "auto", "--output-format", "stream-json", "--verbose"]
    prompt = args[4]
    assert "/compound-engineering:lfg #70" in prompt
    assert "usage limit" in prompt
    assert "reset" in prompt
    assert "continue" in prompt.lower()
    assert "Closes #70" in prompt


def test_a_resume_runs_in_the_markers_worktree_and_appends_to_the_log(tmp_path: Path) -> None:
    worktree = tmp_path / ".claude/worktrees/issue-70-2"
    worktree.mkdir(parents=True)
    log = tmp_path / dispatcher.STATE / "logs/issue-70.log"
    log.parent.mkdir(parents=True)
    earlier = INIT + "\n" + rejected() + "\n"
    log.write_text(earlier)
    marker = Marker(SESSION, "issue-70-2", 1759350600)
    runner, spawn = sessions(tmp_path, FakeGit())
    running = runner.resume(70, marker)
    (_, options), = spawn.calls
    assert options["cwd"] == worktree
    assert options["start_new_session"] is True
    assert options["stdin"] is subprocess.DEVNULL
    assert options["stderr"] is subprocess.STDOUT
    assert options["stdout"].name == str(log)
    assert options["stdout"].mode == "a"
    assert (running.issue, running.branch, running.worktree, running.log) == (
        70, "issue-70-2", worktree, log)
    assert running.since == len(earlier.encode())
    assert running.resumed == marker
    assert log.read_text() == earlier


def test_a_resume_whose_worktree_is_gone_raises_before_spawning(tmp_path: Path) -> None:
    """R9: the issue needs attention with the reason; no claude starts."""
    runner, spawn = sessions(tmp_path, FakeGit())
    with pytest.raises(FileNotFoundError):
        runner.resume(70, Marker(SESSION, "issue-70", 1759350600))
    assert spawn.calls == []


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
                 broken: int | None = None, markers: dict[int, Marker] | None = None) -> None:
        self.answers = issues or {}
        self.records = markers or {}  # each paused issue's valid marker, as its comments hold it
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

    created: list[str] = []

    def ensure_labels(self) -> list[str]:
        self.writes.append("labels")
        return self.created

    def login(self) -> str:
        return "me"

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

    def marker(self, issue: int) -> Marker | None:
        return self.records.get(issue)


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


# The command at the usage limit

class Clock:
    """A wall clock the test sets; `step` seconds pass at every reading."""

    def __init__(self, now: float, step: float = 0.0) -> None:
        self.now = now
        self.step = step

    def __call__(self) -> float:
        now = self.now
        self.now += self.step
        return now


def boss_at(tmp_path: Path, gh: FakeGitHub, slots: int, clock: Clock,
            lines: list[str]) -> tuple[dispatcher.Dispatcher, FakeSpawn]:
    """A dispatcher on this clock, its say lines into `lines`."""
    runner, spawn = sessions(tmp_path, FakeGit())
    return dispatcher.Dispatcher(gh, runner, slots, say=lines.append, clock=clock), spawn


def exits(boss: dispatcher.Dispatcher, issue: int, *events: str) -> None:
    """The issue's session writes these events to its part of the log, then exits with 0."""
    running = boss.running[issue]
    with running.log.open("a") as log:
        log.write("".join(line + "\n" for line in events))
    process = running.process
    assert isinstance(process, FakeProcess)
    process.returncode = 0


def resumes(spawn: FakeSpawn) -> list[tuple[list[str], dict[str, Any]]]:
    return [(args, options) for args, options in spawn.calls if "--resume" in args]


def worktrees(tmp_path: Path, *names: str) -> None:
    for name in names:
        (tmp_path / ".claude/worktrees" / name).mkdir(parents=True)


AT_LIMIT = (INIT, rejected(int(at(20, 30))), result("API Error"))
UNKNOWN = (INIT, result("You've hit your session limit · resets 8:30pm (America/Sao_Paulo)"))


def test_a_session_at_the_limit_is_paused_and_holds_every_start(tmp_path: Path) -> None:
    """AE1: #70 stops at 15:10, resets 20:30; #74 waits although a slot is free, #72 runs on."""
    gh = FakeGitHub({READY: [(ready(70), ()), (ready(72), ())]})
    clock = Clock(at(15))
    lines: list[str] = []
    boss, spawn = boss_at(tmp_path, gh, 2, clock, lines)
    boss.poll()
    gh.answers = {READY: [(ready(74), ())]}
    exits(boss, 70, *AT_LIMIT)
    clock.now = at(15, 10)
    boss.poll()
    pause = gh.writes[-1]
    assert isinstance(pause, Move)
    assert (pause.issue, pause.remove, pause.add, pause.comment_first) == (
        70, (IN_PROGRESS,), (PAUSED,), True)
    assert "20:30" in (pause.comment or "")
    assert (pause.comment or "").splitlines()[-1] == (
        f'<!-- dispatcher-pause {{"session": "{SESSION}", "branch": "issue-70", '
        f'"reset": {int(at(20, 30))}}} -->')
    assert moves(gh) == [(70, (IN_PROGRESS,)), (72, (IN_PROGRESS,)), (70, (PAUSED,))]
    assert list(boss.running) == [72]
    assert len(spawn.calls) == 2
    held = [line for line in lines if "no session starts until" in line]
    assert len(held) == 1
    assert "2026-10-01 20:31" in held[0]
    clock.now = at(15, 15)
    boss.poll()
    assert len(spawn.calls) == 2
    assert moves(gh)[3:] == []
    assert len([line for line in lines if "no session starts until" in line]) == 1


def test_paused_issues_resume_in_their_worktrees_once_the_limit_is_back(tmp_path: Path) -> None:
    """AE2: #70 and #72 resume at 20:35 with their own conversations; #74 waits for a slot."""
    worktrees(tmp_path, "issue-70", "issue-72")
    gh = FakeGitHub({PAUSED: [(paused(70), ()), (paused(72), ())], READY: [(ready(74), ())]},
                    markers={70: Marker(SESSION, "issue-70", int(at(20, 30))),
                             72: Marker(OTHER, "issue-72", int(at(20, 30)))})
    lines: list[str] = []
    boss, spawn = boss_at(tmp_path, gh, 2, Clock(at(20, 35)), lines)
    boss.poll()
    (first, first_options), (second, second_options) = spawn.calls
    assert first[:4] == ["claude", "-p", "--resume", SESSION]
    assert second[:4] == ["claude", "-p", "--resume", OTHER]
    assert first_options["cwd"] == tmp_path / ".claude/worktrees/issue-70"
    assert second_options["cwd"] == tmp_path / ".claude/worktrees/issue-72"
    assert gh.writes == [Move(70, (PAUSED, READY, NEEDS_ATTENTION), (IN_PROGRESS,)),
                         Move(72, (PAUSED, READY, NEEDS_ATTENTION), (IN_PROGRESS,))]
    assert {issue: running.branch for issue, running in boss.running.items()} == {
        70: "issue-70", 72: "issue-72"}
    log = tmp_path / dispatcher.STATE / "logs/issue-70.log"
    assert (f"dispatcher: #70 resumed in {tmp_path}/.claude/worktrees/issue-70, log {log}"
            in lines)


def test_a_resumed_session_that_opens_its_pull_request_goes_in_review(tmp_path: Path) -> None:
    """AE3: the marker's branch finds the pull request, then promotes it once its checks pass."""
    worktrees(tmp_path, "issue-70-2")
    gh = FakeGitHub({PAUSED: [(paused(70), ())]}, head={"issue-70-2": (PR,)},
                    markers={70: Marker(SESSION, "issue-70-2", int(at(20, 30)))})
    boss, _ = boss_at(tmp_path, gh, 1, Clock(at(20, 35)), [])
    boss.poll()
    gh.answers = {}
    exits(boss, 70, INIT, result("Done.", error=False))
    boss.poll()
    assert moves(gh)[1:] == [(70, (IN_REVIEW,))]
    assert Link(101, 70) in gh.writes
    gh.answers = {IN_REVIEW: [(Issue(70, frozenset({IN_REVIEW})), ())]}
    gh.checks = True
    boss.poll()
    assert moves(gh)[2:] == [(70, (READY_TO_MERGE,))]


def test_a_session_ended_with_its_pull_request_open_carries_its_progress(tmp_path: Path) -> None:
    """The in-review report needs the log's marks; the limit still counts only without a PR."""
    gh = FakeGitHub({READY: [(ready(74), ())]}, head={"issue-74": (PR,)})
    boss, _ = boss_at(tmp_path, gh, 1, Clock(at(15)), [])
    boss.poll()
    exits(boss, 74, INIT, *(json.dumps(skill(name)) for name in (
        "ce-plan", "ce-doc-review", "ce-work", "ce-code-review", "ce-commit-push-pr")),
          json.dumps(says("Pull request #101 is open.")), rejected(), result("API Error"))
    session = boss.read(boss.running[74])
    assert session.progress == dispatcher.Progress(marks("done", "done", "done", "done", "current"),
                                                   "Pull request #101 is open.")
    assert (session.reason, session.limit) == ("", None)


def resumed_once(tmp_path: Path, marker: Marker) -> tuple[dispatcher.Dispatcher, FakeGitHub]:
    """A dispatcher that resumed #70 from `marker`; #70 is no longer among the paused issues."""
    worktrees(tmp_path, marker.branch)
    gh = FakeGitHub({PAUSED: [(paused(70), ())]}, markers={70: marker})
    boss, _ = boss_at(tmp_path, gh, 1, Clock(at(20, 35)), [])
    boss.poll()
    gh.answers = {}
    return boss, gh


def test_a_resumed_session_at_the_limit_again_comments_its_new_reset(tmp_path: Path) -> None:
    """AE3, KTD5: the reset is news, so the pause comments again."""
    boss, gh = resumed_once(tmp_path, Marker(SESSION, "issue-70", None))
    exits(boss, 70, INIT, rejected(int(at(22))), result("API Error"))
    boss.poll()
    pause = gh.writes[-1]
    assert isinstance(pause, Move)
    assert (pause.remove, pause.add) == ((IN_PROGRESS,), (PAUSED,))
    assert (pause.comment or "").splitlines()[-1] == (
        f'<!-- dispatcher-pause {{"session": "{SESSION}", "branch": "issue-70", '
        f'"reset": {int(at(22))}}} -->')


def test_a_resumed_session_at_the_limit_again_with_nothing_new_does_not_comment(
        tmp_path: Path) -> None:
    """KTD5: the same session, the reset still unknown: the labels swap, no comment."""
    boss, gh = resumed_once(tmp_path, Marker(SESSION, "issue-70", None))
    exits(boss, 70, *UNKNOWN)
    boss.poll()
    assert gh.writes[-1] == Move(70, (IN_PROGRESS,), (PAUSED,))


def test_a_paused_issue_past_its_reset_resumes_after_a_restart(tmp_path: Path) -> None:
    """AE4: started again at 21:00, #70 is no orphan and resumes at the first poll."""
    worktrees(tmp_path, "issue-70")
    gh = FakeGitHub({PAUSED: [(paused(70), ())]},
                    markers={70: Marker(SESSION, "issue-70", int(at(20, 30)))})
    lines: list[str] = []
    boss, spawn = boss_at(tmp_path, gh, 2, Clock(at(21)), lines)
    boss.start()
    assert gh.writes == ["labels"]
    assert not [line for line in lines if "usage limit" in line]
    boss.poll()
    assert [args[3] for args, _ in resumes(spawn)] == [SESSION]
    assert moves(gh) == [(70, (IN_PROGRESS,))]


def test_a_paused_issue_before_its_reset_holds_after_a_restart(tmp_path: Path) -> None:
    """AE4: started again at 18:00, the hold comes back from the marker alone."""
    worktrees(tmp_path, "issue-70")
    gh = FakeGitHub({PAUSED: [(paused(70), ())], READY: [(ready(74), ())]},
                    markers={70: Marker(SESSION, "issue-70", int(at(20, 30)))})
    lines: list[str] = []
    clock = Clock(at(18))
    boss, spawn = boss_at(tmp_path, gh, 2, clock, lines)
    boss.start()
    held = [line for line in lines if "no session starts until" in line]
    assert len(held) == 1
    assert "2026-10-01 20:31" in held[0]
    clock.now = at(18, 5)
    boss.poll()
    assert spawn.calls == []
    assert gh.writes == ["labels"]


def test_an_unknown_reset_holds_its_poll_then_probes_with_one_session(tmp_path: Path) -> None:
    """AE6: no start at poll k; #70 alone at k+1; #72 at k+2 while #70 runs."""
    gh = FakeGitHub({READY: [(ready(70), ())]},
                    markers={72: Marker(OTHER, "issue-72", int(at(14)))})
    lines: list[str] = []
    clock = Clock(at(15))
    boss, spawn = boss_at(tmp_path, gh, 2, clock, lines)
    boss.poll()
    worktrees(tmp_path, "issue-70", "issue-72")
    gh.answers = {PAUSED: [(paused(72), ())], READY: [(ready(74), ())]}
    exits(boss, 70, *UNKNOWN)
    clock.now = at(15, 10)
    boss.poll()  # poll k
    assert len(spawn.calls) == 1
    assert moves(gh) == [(70, (IN_PROGRESS,)), (70, (PAUSED,))]
    assert lines.count("dispatcher: the Claude usage limit is spent and its reset is unknown; "
                       "one session is tried at the next poll") == 1
    gh.answers = {PAUSED: [(paused(70), ()), (paused(72), ())], READY: [(ready(74), ())]}
    gh.records[70] = Marker(SESSION, "issue-70", None)
    clock.now = at(15, 15)
    boss.poll()  # poll k+1
    assert [args[3] for args, _ in resumes(spawn)] == [SESSION]
    gh.answers = {PAUSED: [(paused(72), ())], READY: [(ready(74), ())]}
    clock.now = at(15, 20)
    boss.poll()  # poll k+2
    assert [args[3] for args, _ in resumes(spawn)] == [SESSION, OTHER]
    assert sorted(boss.running) == [70, 72]


def test_an_unknown_reset_holds_its_poll_on_a_clock_that_moves_at_every_reading(
        tmp_path: Path) -> None:
    """KTD4: the poll reads the clock once, so the hold it made at `now` still holds its tick."""
    gh = FakeGitHub({READY: [(ready(70), ())]})
    clock = Clock(at(15), step=1.0)
    boss, spawn = boss_at(tmp_path, gh, 2, clock, [])
    boss.poll()
    gh.answers = {READY: [(ready(74), ())]}
    exits(boss, 70, *UNKNOWN)
    boss.poll()
    assert len(spawn.calls) == 1
    assert moves(gh) == [(70, (IN_PROGRESS,)), (70, (PAUSED,))]


def test_an_issue_whose_paused_label_was_removed_never_resumes(tmp_path: Path) -> None:
    """AE7: past the reset and after a restart, #70 is no longer paused: no resume."""
    gh = FakeGitHub({READY: [(ready(70), ())]},
                    markers={70: Marker(SESSION, "issue-70", int(at(20, 30)))})
    clock = Clock(at(15))
    boss, spawn = boss_at(tmp_path, gh, 1, clock, [])
    boss.poll()
    worktrees(tmp_path, "issue-70")
    gh.answers = {}
    exits(boss, 70, *AT_LIMIT)
    clock.now = at(15, 10)
    boss.poll()
    assert moves(gh)[-1] == (70, (PAUSED,))
    clock.now = at(21)
    boss.poll()
    again, spawn_again = boss_at(tmp_path, gh, 1, Clock(at(21)), [])
    again.start()
    again.poll()
    assert resumes(spawn) == []
    assert spawn_again.calls == []
    assert moves(gh) == [(70, (IN_PROGRESS,)), (70, (PAUSED,))]


def test_a_paused_issue_without_a_pause_record_needs_attention(tmp_path: Path) -> None:
    """R9: no valid marker among its comments: paused to needs attention, nothing spawned."""
    gh = FakeGitHub({PAUSED: [(paused(70), ())]})
    boss, spawn = boss_at(tmp_path, gh, 1, Clock(at(21)), [])
    boss.poll()
    move, = gh.writes
    assert isinstance(move, Move)
    assert (move.issue, move.remove, move.add) == (70, (PAUSED,), (NEEDS_ATTENTION,))
    assert "no pause record was found" in (move.comment or "")
    assert spawn.calls == []


def test_a_resume_whose_worktree_is_gone_needs_attention(tmp_path: Path) -> None:
    """R9: in progress first, then needs attention with the reason; the slot stays free."""
    gh = FakeGitHub({PAUSED: [(paused(70), ())]},
                    markers={70: Marker(SESSION, "issue-70", int(at(20, 30)))})
    boss, spawn = boss_at(tmp_path, gh, 1, Clock(at(21)), [])
    boss.poll()
    swap, failure = gh.writes
    assert swap == Move(70, (PAUSED, READY, NEEDS_ATTENTION), (IN_PROGRESS,))
    assert isinstance(failure, Move)
    assert (failure.remove, failure.add) == ((IN_PROGRESS,), (NEEDS_ATTENTION,))
    assert f"{tmp_path}/.claude/worktrees/issue-70" in (failure.comment or "")
    assert "gone" in (failure.comment or "")
    assert spawn.calls == []
    assert boss.running == {}


def test_stopping_leaves_a_paused_issue_alone(tmp_path: Path) -> None:
    """R10: #70 is paused on GitHub, #75 runs: only #75 is ended and marked."""
    gh = FakeGitHub({READY: [(ready(75), ())]},
                    markers={70: Marker(SESSION, "issue-70", int(at(20, 30)))})
    boss, _ = boss_at(tmp_path, gh, 1, Clock(at(18)), [])
    boss.poll()
    gh.answers = {PAUSED: [(paused(70), ())]}
    process = boss.running[75].process
    assert isinstance(process, FakeProcess)
    boss.stop()
    assert process.signals == ["terminate"]
    assert moves(gh) == [(75, (IN_PROGRESS,)), (75, (NEEDS_ATTENTION,))]


def test_stopping_pauses_a_session_that_ended_at_the_limit(tmp_path: Path) -> None:
    """KTD9: #74 hit the limit before Ctrl-C: paused, not needs attention; #75 is ended."""
    gh = FakeGitHub()
    boss, _, live = two_sessions(tmp_path, gh)
    with boss.running[74].log.open("a") as log:
        log.write("".join(line + "\n" for line in AT_LIMIT))
    boss.stop()
    assert live.signals == ["terminate"]
    assert moves(gh)[2:] == [(74, (PAUSED,)), (75, (NEEDS_ATTENTION,))]


def test_a_pause_that_fails_to_write_still_holds_and_is_retried_once(tmp_path: Path) -> None:
    """The hold is read from the log before any write; the move waits in `pending`."""
    gh = FakeGitHub({READY: [(ready(70), ())]})
    clock = Clock(at(15))
    boss, spawn = boss_at(tmp_path, gh, 1, clock, [])
    boss.poll()
    gh.answers = {READY: [(ready(74), ())]}
    exits(boss, 70, *AT_LIMIT)
    gh.flaky = {"move"}
    clock.now = at(15, 10)
    boss.poll()
    assert moves(gh) == [(70, (IN_PROGRESS,))]
    assert len(spawn.calls) == 1
    clock.now = at(15, 15)
    boss.poll()
    assert moves(gh) == [(70, (IN_PROGRESS,)), (70, (PAUSED,))]
    clock.now = at(15, 20)
    boss.poll()
    assert moves(gh) == [(70, (IN_PROGRESS,)), (70, (PAUSED,))]
    assert len(spawn.calls) == 1


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
    assert boss.calls == ["start", "dispatcher: a poll every 0s; Ctrl-C stops", "poll",
                          "dispatcher: stopping", "stop"]


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


# What it says (the command's output)

def test_start_says_what_it_watches(tmp_path: Path) -> None:
    """Started with nothing to do, it still says it runs, for whom and with how many sessions."""
    runner, _ = sessions(tmp_path, FakeGit())
    lines: list[str] = []
    dispatcher.Dispatcher(FakeGitHub(), runner, 3, say=lines.append).start()
    assert lines
    assert "me" in lines[0]
    assert "`ready`" in lines[0]
    assert "3 sessions" in lines[0]


def test_every_poll_says_what_it_found(tmp_path: Path) -> None:
    """A poll with nothing to dispatch still reports the queue, the sessions and the reviews."""
    gh = FakeGitHub({READY: [(ready(70), ()), (ready(72, blocked=1), ())],
                     IN_REVIEW: [(Issue(69, frozenset({IN_REVIEW})), ())]})
    runner, _ = sessions(tmp_path, FakeGit())
    lines: list[str] = []
    dispatcher.Dispatcher(gh, runner, 0, say=lines.append).poll()
    summary, = [line for line in lines if "ready (" in line]
    assert "2 ready (1 blocked)" in summary
    assert "0 running" in summary
    assert "1 in review" in summary


def test_an_empty_poll_is_not_silent(tmp_path: Path) -> None:
    runner, _ = sessions(tmp_path, FakeGit())
    lines: list[str] = []
    dispatcher.Dispatcher(FakeGitHub(), runner, 2, say=lines.append).poll()
    assert any("0 ready" in line for line in lines)


def test_lines_carry_the_time_and_are_flushed(capsys: pytest.CaptureFixture[str]) -> None:
    dispatcher.stamp("dispatcher: hello")
    out = capsys.readouterr().out
    assert re.fullmatch(r"\d\d:\d\d:\d\d dispatcher: hello\n", out)


@pytest.mark.usefixtures("handlers")
def test_serve_says_how_often_it_polls() -> None:
    boss = Boss(lambda: signal.raise_signal(signal.SIGINT))
    dispatcher.serve(boss, 0)  # type: ignore[arg-type]
    assert any("every 0s" in call for call in boss.calls)


def test_each_ready_issue_says_what_happens_to_it() -> None:
    """Dispatched, blocked, waiting for a slot or already running: each ready issue gets a line."""
    queue = (Issue(70, frozenset({READY}), 0, "Add the gate"),
             Issue(72, frozenset({READY}), 1, "Gate alerts"),
             Issue(73, frozenset({READY}), 0, "Pool goal"),
             Issue(74, frozenset({READY, IN_PROGRESS}), 0, "Pump"))
    lines = dispatcher.queue_lines(queue, running=set(), picked=[70], slots=1)
    assert lines == [
        '#70 "Add the gate": dispatching',
        '#72 "Gate alerts": blocked by 1 open issue, skipped',
        '#73 "Pool goal": waiting for a free session (1 of 1 in use)',
        '#74 "Pump": already in progress',
    ]


def test_while_the_limit_holds_a_ready_issue_waits_for_it() -> None:
    """R14: held, a free session isn't what a ready issue waits for."""
    queue = (Issue(73, frozenset({READY}), 0, "Pool goal"),
             Issue(72, frozenset({READY}), 1, "Gate alerts"))
    lines = dispatcher.queue_lines(queue, running=set(), picked=[], slots=2, held=True)
    assert lines == ['#73 "Pool goal": waiting for the Claude usage limit to reset',
                     '#72 "Gate alerts": blocked by 1 open issue, skipped']


def test_a_poll_says_it_reads_github_and_what_runs_and_waits(tmp_path: Path) -> None:
    gh = FakeGitHub({READY: [(Issue(70, frozenset({READY}), 0, "Add the gate"), ())],
                     IN_REVIEW: [(Issue(69, frozenset({IN_REVIEW})), (PR,))]})
    runner, _ = sessions(tmp_path, FakeGit())
    lines: list[str] = []
    boss = dispatcher.Dispatcher(gh, runner, 1, say=lines.append)
    boss.poll()
    text = "\n".join(lines)
    assert "reading GitHub" in lines[0]
    assert '#70 "Add the gate": dispatching' in text
    assert "#69 in review: its required checks don't all pass yet" in text
    assert "creating its worktree" in text
    assert "claude started" in text
    lines.clear()
    boss.poll()
    assert any("#70 still running" in line for line in lines)


def test_an_ended_session_says_how_it_ended(tmp_path: Path) -> None:
    gh = FakeGitHub({READY: [(ready(74), ())]}, head={"issue-74": (PR,)})
    runner, _ = sessions(tmp_path, FakeGit())
    lines: list[str] = []
    boss = dispatcher.Dispatcher(gh, runner, 1, say=lines.append)
    boss.poll()
    process = boss.running[74].process
    assert isinstance(process, FakeProcess)
    process.returncode = 0
    gh.answers = {}
    lines.clear()
    boss.poll()
    assert any("#74 session ended (exit code 0)" in line for line in lines)


def test_start_says_what_it_found_and_fixed(tmp_path: Path) -> None:
    gh = FakeGitHub({IN_PROGRESS: [(Issue(74, frozenset({IN_PROGRESS})), ())]})
    gh.created = ["ready to merge"]
    runner, _ = sessions(tmp_path, FakeGit())
    runner.git = lambda args: ""
    lines: list[str] = []
    dispatcher.Dispatcher(gh, runner, 2, say=lines.append).start()
    text = "\n".join(lines)
    assert "created the label `ready to merge`" in text
    assert "#74 was left in progress" in text


def test_start_with_nothing_to_fix_says_so(tmp_path: Path) -> None:
    runner, _ = sessions(tmp_path, FakeGit())
    lines: list[str] = []
    dispatcher.Dispatcher(FakeGitHub(), runner, 2, say=lines.append).start()
    text = "\n".join(lines)
    assert "labels: all 6 in place" in text
    assert "no issue left in progress" in text


@pytest.mark.usefixtures("handlers")
def test_serve_says_when_the_next_poll_comes() -> None:
    polls = iter([None, "stop"])

    def polled() -> None:
        if next(polls) == "stop":
            signal.raise_signal(signal.SIGINT)

    boss = Boss(polled)
    dispatcher.serve(boss, 0)  # type: ignore[arg-type]
    assert any(call.startswith("dispatcher: next poll at ") for call in boss.calls)


def test_issues_carry_their_title() -> None:
    gh, _ = github((("api", "graphql"), 0, nodes(dict(node(70, ("ready",)), title="Add the gate"))))
    (issue, _), = gh.issues(READY)
    assert issue.title == "Add the gate"


def test_ensure_labels_returns_what_it_created() -> None:
    gh, _ = github((("label", "list"), 0, json.dumps([{"name": READY}])))
    assert gh.ensure_labels() == [IN_PROGRESS, IN_REVIEW, READY_TO_MERGE, NEEDS_ATTENTION, PAUSED]
