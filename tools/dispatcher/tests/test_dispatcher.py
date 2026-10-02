"""tools/dispatcher/dispatcher.py: the author's ready issues become pull requests."""

from collections.abc import Callable, Iterator
import contextlib
import dataclasses
from datetime import datetime
import fcntl
import itertools
import json
import os
from pathlib import Path
import re
import signal
import subprocess
from typing import Any

import pytest

import dispatcher
from dispatcher import (IN_PROGRESS, IN_REVIEW, INTERRUPTED, LIMIT, NEEDS_ATTENTION, PAUSED,
                        READY, READY_TO_MERGE, STOPPED, Dispatch, Ended, Hold, Issue, Link, Marker,
                        Move, Progress, PullRequest, Report, Resume, Review, Snapshot, Status)

PR = PullRequest(101, "https://github.com/o/r/pull/101")
SESSION = "3f2a9c1e-8b4d-4e6f-9a0b-1c2d3e4f5a6b"
REPO = Path("/repo")  # the checkout the pure examples' paths sit in


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
          resumed: Marker | None = None, progress: Progress = Progress(), **more: Any) -> Ended:
    """#issue's ended session; `more` sets the rest of its fields (`stopped`, `at_start`…)."""
    return dataclasses.replace(
        Ended(issue, f"/repo/.claude/worktrees/issue-{issue}",
              "/repo/tools/dispatcher/.state/logs/x.log", reason, prs, linked, limit, resumed,
              progress, branch=f"issue-{issue}"), **more)


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
    move, report = dispatcher.judge(ended(74, prs=(PR,), linked=frozenset({101})), REPO)
    assert isinstance(move, Move)
    assert isinstance(report, Report)
    assert (move.issue, move.remove, move.add) == (74, (IN_PROGRESS,), (IN_REVIEW,))
    assert PR.url in (move.comment or "")
    assert dispatcher.tick(Snapshot(ready=(ready(75),)), set(), 1) == [Dispatch(75)]


def test_a_pull_request_not_linked_to_its_issue_gets_the_link() -> None:
    """AE1 relies on merging closing the issue: the dispatcher adds Closes #N."""
    assert Link(101, 74) in dispatcher.judge(ended(74, prs=(PR,)), REPO)
    linked = dispatcher.judge(ended(74, prs=(PR,), linked=frozenset({101})), REPO)
    assert not [action for action in linked if isinstance(action, Link)]


def test_a_session_without_a_pull_request_needs_attention() -> None:
    """AE5: the reason and the worktree in the comment."""
    move, report = dispatcher.judge(ended(74), REPO)
    assert isinstance(move, Move)
    assert isinstance(report, Report)
    assert (move.remove, move.add) == ((IN_PROGRESS,), (NEEDS_ATTENTION,))
    assert "lfg stopped: no work source" in (move.comment or "")
    assert "Worktree: `.claude/worktrees/issue-74`" in (move.comment or "")


def test_comments_name_paths_inside_the_checkout() -> None:
    """AE8, R15: a comment is public, so the machine's folders never show, the reason's either."""
    root = Path("/Users/me/pururu-ha")
    session = dataclasses.replace(
        ended(70, reason=f"Uncommitted changes are left in {root}/.claude/worktrees/issue-70."),
        worktree=f"{root}/.claude/worktrees/issue-70",
        log=f"{root}/tools/dispatcher/.state/logs/issue-70.log")
    attention, _ = dispatcher.judge(session, root)
    for move in (attention, dispatcher.pause(session, limit(70), root),
                 dispatcher.pause(session, cause(70, INTERRUPTED), root)):
        assert isinstance(move, Move)
        comment = move.comment or ""
        assert "Worktree: `.claude/worktrees/issue-70`" in comment
        assert "Log: `tools/dispatcher/.state/logs/issue-70.log`" in comment
        assert "/Users/" not in comment
    assert "left in .claude/worktrees/issue-70." in (attention.comment or "")


def test_a_path_outside_the_checkout_is_named_by_its_last_part() -> None:
    root = Path("/Users/me/pururu-ha")
    assert dispatcher.inside(root / ".claude/worktrees/issue-70", root) == (
        ".claude/worktrees/issue-70")
    assert dispatcher.inside("/tmp/issue-70.log", root) == "issue-70.log"


# The usage limit

def test_a_session_stopped_by_the_limit_is_paused_with_its_marker() -> None:
    """AE1: #70 stops at 15:10 with `resets 8:30pm`: paused, the comment first, naming 20:30."""
    reset = int(at(20, 30))
    move, report = dispatcher.judge(ended(70, limit=limit(70)), REPO)
    assert isinstance(move, Move)
    assert isinstance(report, Report)
    assert (move.issue, move.remove, move.add, move.comment_first) == (
        70, (IN_PROGRESS,), (PAUSED,), True)
    comment = move.comment or ""
    assert "usage limit" in comment
    assert "20:30" in comment
    assert SESSION in comment
    assert "Worktree: `.claude/worktrees/issue-70`" in comment
    assert "Log: `tools/dispatcher/.state/logs/x.log`" in comment
    assert comment.splitlines()[-1] == (
        '<!-- dispatcher-pause {"session": "3f2a9c1e-8b4d-4e6f-9a0b-1c2d3e4f5a6b", '
        f'"branch": "issue-70", "reset": {reset}, "cause": "limit"}} -->')


def test_a_limit_with_no_reset_says_it_is_tried_again_at_the_next_poll() -> None:
    """R5: no reset in the message: the comment says so, the marker's reset is null."""
    move, report = dispatcher.judge(ended(70, limit=limit(70, reset=None)), REPO)
    assert isinstance(move, Move)
    assert isinstance(report, Report)
    assert move.add == (PAUSED,)
    comment = move.comment or ""
    assert "next poll" in comment
    assert comment.splitlines()[-1].endswith(
        '"branch": "issue-70", "reset": null, "cause": "limit"} -->')


def test_a_limit_after_the_pull_request_is_open_is_in_review() -> None:
    move, report = dispatcher.judge(ended(70, prs=(PR,), linked=frozenset({101}),
                                          limit=limit(70)), REPO)
    assert isinstance(move, Move)
    assert isinstance(report, Report)
    assert move.add == (IN_REVIEW,)


def test_a_resumed_session_that_opens_its_pull_request_is_in_review() -> None:
    """AE3: #70 resumed, then opened its pull request and ended."""
    move, report = dispatcher.judge(ended(70, prs=(PR,), linked=frozenset({101}),
                                          resumed=limit(70)), REPO)
    assert isinstance(move, Move)
    assert isinstance(report, Report)
    assert (move.remove, move.add) == ((IN_PROGRESS,), (IN_REVIEW,))


def test_a_resumed_session_paused_again_comments_only_on_news() -> None:
    """KTD5: a new reset is news; the same session with the same reset is not."""
    unknown = limit(70, reset=None)
    news, _ = dispatcher.judge(ended(70, limit=limit(70), resumed=unknown), REPO)
    assert isinstance(news, Move)
    assert news.add == (PAUSED,)
    assert "20:30" in (news.comment or "")
    same, _ = dispatcher.judge(ended(70, limit=limit(70, reset=None), resumed=unknown), REPO)
    assert same == Move(70, (IN_PROGRESS,), (PAUSED,))


def cause(issue: int, kind: str, session: str = SESSION) -> Marker:
    """A marker pausing the issue for `kind`, its reset unknown (only the limit has one)."""
    return Marker(session, f"issue-{issue}", None, kind)


@pytest.mark.parametrize("kind, says", [
    (INTERRUPTED, "the session was interrupted (found gone when the dispatcher started)."),
    (STOPPED, "the session was stopped with `dispatcher.py stop`.")])
def test_a_pause_says_its_cause_and_speaks_of_no_reset(kind: str, says: str) -> None:
    """KTD4: interrupted and stopped pauses carry their cause in the marker; no limit, no reset."""
    move = dispatcher.pause(ended(70), cause(70, kind), REPO)
    assert (move.issue, move.remove, move.add, move.comment_first) == (
        70, (IN_PROGRESS,), (PAUSED,), True)
    comment = move.comment or ""
    assert comment.startswith(f"Dispatcher: {says}\n\n")
    said = "\n".join(comment.splitlines()[:-1])  # the marker's fields aside
    assert "usage limit" not in said
    assert "reset" not in said
    assert "Worktree: `.claude/worktrees/issue-70`" in comment
    assert comment.splitlines()[-1] == (
        f'<!-- dispatcher-pause {{"session": "{SESSION}", "branch": "issue-70", "reset": null, '
        f'"cause": "{kind}"}} -->')


def test_a_resumed_session_paused_again_comments_only_on_a_new_cause() -> None:
    """KTD4: the same cause with nothing new swaps the labels alone; another cause is news."""
    interrupted = cause(70, INTERRUPTED)
    resumed = ended(70, resumed=interrupted)
    assert dispatcher.pause(resumed, interrupted, REPO) == Move(70, (IN_PROGRESS,), (PAUSED,))
    stopped = dispatcher.pause(resumed, cause(70, STOPPED), REPO)
    assert "`dispatcher.py stop`" in (stopped.comment or "")
    limited = dispatcher.pause(resumed, cause(70, LIMIT), REPO)
    assert "usage limit" in (limited.comment or "")


def gone(issue: int, **more: Any) -> Ended:
    """#issue's session found gone at start: no final result, its conversation known."""
    fields: dict[str, Any] = {"reason": "the session ended with no final result",
                              "final": False, "conversation": SESSION, "at_start": True}
    return ended(issue, **{**fields, **more})


def test_a_session_found_gone_at_start_without_a_final_result_is_paused_as_interrupted() -> None:
    """R7, KTD3, KTD9: its conversation's marker, and the reached stage paused."""
    reached = marks("done", "done", "current")
    move, report = dispatcher.judge(gone(70, progress=Progress(reached)), REPO)
    assert isinstance(move, Move)
    assert (move.remove, move.add, move.comment_first) == ((IN_PROGRESS,), (PAUSED,), True)
    assert dispatcher.marker_of(move.comment or "", 70) == cause(70, INTERRUPTED)
    assert "the session was interrupted" in (move.comment or "")
    assert report == Report(70, Status(PAUSED, marks("done", "done", "paused"),
                                       cause=INTERRUPTED))


def test_a_session_resumed_and_found_gone_with_its_own_marker_pauses_without_a_comment() -> None:
    """KTD4: interrupted again before anything new, the marker it came from still resumes it."""
    move, _ = dispatcher.judge(gone(70, resumed=cause(70, INTERRUPTED)), REPO)
    assert move == Move(70, (IN_PROGRESS,), (PAUSED,))


@pytest.mark.parametrize("more", [{"at_start": False}, {"conversation": None}],
                         ids=["at a poll", "no conversation"])
def test_no_final_result_needs_attention_at_a_poll_or_with_no_conversation(
        more: dict[str, Any]) -> None:
    """KTD3: a session that keeps dying never loops through resumes; R9: nothing to resume."""
    move, report = dispatcher.judge(gone(70, **more), REPO)
    assert isinstance(move, Move)
    assert move.add == (NEEDS_ATTENTION,)
    assert "no final result" in (move.comment or "")
    assert isinstance(report, Report)
    assert report.status.state == NEEDS_ATTENTION


@pytest.mark.parametrize(("more", "verdict", "kind"), [
    ({"prs": (PR,), "limit": limit(70), "stopped": True}, IN_REVIEW, None),
    ({"limit": limit(70), "stopped": True}, PAUSED, LIMIT),
    ({"stopped": True, "final": True}, PAUSED, STOPPED),
    ({"stopped": True, "at_start": False}, PAUSED, STOPPED),
    ({"final": True}, NEEDS_ATTENTION, None),
    ({}, PAUSED, INTERRUPTED),
], ids=["pull request first", "then the limit", "then stopped", "stopped at a poll too",
        "then a final result", "then interrupted"])
def test_one_verdict_order_for_every_ended_session(more: dict[str, Any], verdict: str,
                                                   kind: str | None) -> None:
    """KTD3: pull request, limit, stopped, final result, then no final result."""
    actions = dispatcher.judge(gone(70, **more), REPO)
    move = actions[0]
    assert isinstance(move, Move)
    assert move.add == (verdict,)
    if kind is not None:
        marker = dispatcher.marker_of(move.comment or "", 70)
        assert marker is not None
        assert marker.cause == kind
        report = actions[1]
        assert isinstance(report, Report)
        assert report.status.cause == kind


def test_a_stopped_session_with_no_conversation_needs_attention() -> None:
    """Nothing to resume, whatever paused it."""
    move, _ = dispatcher.judge(gone(70, stopped=True, conversation=None), REPO)
    assert isinstance(move, Move)
    assert move.add == (NEEDS_ATTENTION,)


def test_needs_attention_removes_the_label_it_is_given() -> None:
    """R9: a resume that cannot start leaves `paused`."""
    move = dispatcher.needs_attention(70, "the resume could not start.", remove=PAUSED)
    assert (move.remove, move.add) == ((PAUSED,), (NEEDS_ATTENTION,))


def test_no_session_starts_while_the_limit_holds() -> None:
    """AE1: a free slot and a ready #74, but the hold runs to 20:31; the promotion still goes."""
    snapshot = Snapshot(reviews=(Review(72, True),), ready=(ready(74),))
    assert dispatcher.tick(snapshot, set(), 2, at(15, 10), Hold(at(20, 31))) == [
        Move(72, (IN_REVIEW,), (READY_TO_MERGE,)),
        Report(72, Status(READY_TO_MERGE), dispatcher.marks_passed)]


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


def test_only_the_limits_markers_hold_at_start() -> None:
    """AE7, KTD4: an interrupted or stopped pause neither holds nor probes; a limit still does."""
    others = [cause(70, INTERRUPTED), cause(72, STOPPED)]
    assert dispatcher.restore(others, at(18)) == Hold()
    assert dispatcher.restore([*others, limit(73, reset=None)], at(18)) == Hold(at(18), probe=True)


def test_an_unknown_reset_probes_whatever_order_a_past_reset_comes_in() -> None:
    """KTD4, KTD8: a reset already past never cancels the probe an unknown reset asks for."""
    unknown, past = limit(70, reset=None), limit(72, reset=at(17))
    assert dispatcher.restore([unknown, past], at(18)) == Hold(at(18), probe=True)
    assert dispatcher.restore([past, unknown], at(18)) == Hold(at(18), probe=True)


# Promotion

def test_an_issue_in_review_whose_checks_pass_is_ready_to_merge() -> None:
    """AE4, later: every required check passes."""
    assert dispatcher.tick(Snapshot(reviews=(Review(74, True),)), set(), 1) == [
        Move(74, (IN_REVIEW,), (READY_TO_MERGE,)),
        Report(74, Status(READY_TO_MERGE), dispatcher.marks_passed)]


def test_pending_or_failing_checks_leave_it_in_review() -> None:
    assert dispatcher.tick(Snapshot(reviews=(Review(74, False),)), set(), 1) == [
        Report(74, Status(IN_REVIEW), dispatcher.marks_kept)]


def test_each_verdict_is_followed_by_its_final_report() -> None:
    """KTD5: in review, needs attention or paused, from the ended session's own marks; edit only."""
    progress = Progress(marks("done", "done", "current"), AE2_SENTENCE)
    opened = dispatcher.judge(ended(74, prs=(PR,), progress=progress), REPO)
    assert opened[1:] == [Report(74, Status(IN_REVIEW, ("done", "done", "done", "skipped", "done",
                                                         "current"))), Link(101, 74)]
    failed = dispatcher.judge(ended(74, progress=progress), REPO)
    assert failed[1:] == [Report(74, Status(NEEDS_ATTENTION, marks("done", "done", "failed")))]
    stopped = dispatcher.judge(ended(74, limit=limit(74), progress=progress), REPO)
    assert stopped[1:] == [Report(74, Status(PAUSED, marks("done", "done", "paused"),
                                             reset=at(20, 30), cause=LIMIT))]


def test_a_promotion_reports_ready_to_merge_and_the_rest_in_review_as_they_stand() -> None:
    """AE6, AE8: CI done on the comment's marks; the others edited only, their marks kept."""
    snapshot = Snapshot(reviews=(Review(74, True), Review(60, False)))
    assert dispatcher.tick(snapshot, set(), 1) == [
        Move(74, (IN_REVIEW,), (READY_TO_MERGE,)),
        Report(74, Status(READY_TO_MERGE), dispatcher.marks_passed),
        Report(60, Status(IN_REVIEW), dispatcher.marks_kept)]
    assert dispatcher.marks_kept(marks("done", "current")) == marks("done", "current")


# Start

def test_an_in_progress_issue_at_start_needs_attention() -> None:
    """AE6: the orphan fails with its worktree; issues in review are not in the input at all."""
    move, report = dispatcher.orphans([Issue(74, frozenset({IN_PROGRESS}))],
                                      {74: ["/repo/.claude/worktrees/issue-74"]}, REPO)
    assert isinstance(move, Move)
    assert (move.issue, move.remove, move.add) == (74, (IN_PROGRESS,), (NEEDS_ATTENTION,))
    assert "Worktree: `.claude/worktrees/issue-74`" in (move.comment or "")
    assert "/repo" not in (move.comment or "")
    assert report == Report(74, Status(NEEDS_ATTENTION), dispatcher.marks_stopped)


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
         "The usage limit, an interruption or dispatcher.py stop paused the session; "
         "it resumes later"]]


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


@pytest.mark.parametrize("kind", [LIMIT, INTERRUPTED, STOPPED])
def test_a_marker_round_trips_its_cause(kind: str) -> None:
    """KTD4: the cause is in the line, and a marker of another cause is another marker."""
    marker = Marker(SESSION, "issue-70", 1759350600, kind)
    assert dispatcher.marker_of(f"Dispatcher: paused.\n\n{marker.line()}", 70) == marker
    assert all(marker != dataclasses.replace(marker, cause=other)
               for other in (LIMIT, INTERRUPTED, STOPPED) if other != kind)


def test_a_marker_written_before_its_cause_reads_as_the_limit() -> None:
    """KTD4: markers already posted keep working."""
    gh, _ = github(comments_reply(pause_comment("me", SESSION, "issue-70", 1759350600)))
    assert gh.marker(70) == Marker(SESSION, "issue-70", 1759350600, LIMIT)


@pytest.mark.parametrize("value", ["tired", None, 3, "LIMIT"])
def test_a_marker_with_an_unknown_cause_is_refused(value: object) -> None:
    record = json.dumps({"session": SESSION, "branch": "issue-70", "reset": None,
                         "cause": value})
    assert dispatcher.marker_of(f"Dispatcher: paused.\n\n<!-- dispatcher-pause {record} -->",
                                70) is None


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

    def __init__(self, *branches: str, fail: str = "", stderr: str = "fatal: no space") -> None:
        self.branches = set(branches)
        self.fail = fail
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        if self.fail and args[:2] == self.fail.split():
            raise subprocess.CalledProcessError(128, ["git", *args], stderr=self.stderr)
        if args[:2] == ["branch", "--list"]:
            return "\n".join(f"  {name}" for name in self.branches if name == args[2])
        return ""


class FakeProcess:
    pids = itertools.count(4000)  # each one's PID, never one a real process is known to have

    def __init__(self, *, stubborn: bool = False) -> None:
        self.pid = next(self.pids)
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
        self.processes: list[FakeProcess] = []

    def __call__(self, args: list[str], **options: Any) -> FakeProcess:
        self.calls.append((args, options))
        self.processes.append(FakeProcess())
        return self.processes[-1]


START = "Thu Oct  1 18:10:00 2026"  # what `ps -o lstart=` prints under TZ=UTC and LC_ALL=C


class FakePs:
    """`ps -o lstart=` for one PID: its start time in `starts` (None: gone), else `default`."""

    def __init__(self) -> None:
        self.starts: dict[int, str | None] = {}
        self.default: str | None = START
        self.calls: list[int] = []

    def __call__(self, pid: int) -> str | None:
        self.calls.append(pid)
        return self.starts.get(pid, self.default)


class FakeKillpg:
    """`os.killpg`: records each signal; a group sent SIGTERM or SIGKILL is gone from `ps`,
    unless `stubborn` and only terminated."""

    def __init__(self, ps: FakePs, *, stubborn: bool = False) -> None:
        self.ps = ps
        self.stubborn = stubborn
        self.calls: list[tuple[int, int]] = []

    def __call__(self, pid: int, signum: int) -> None:
        self.calls.append((pid, signum))
        if signum == signal.SIGKILL or not self.stubborn:
            self.ps.starts[pid] = None


def sessions(tmp_path: Path, git: FakeGit) -> tuple[dispatcher.Sessions, FakeSpawn]:
    """Sessions over fakes: `git`, a spawn, `ps` and `killpg` (`fakes` gives the last two)."""
    spawn = FakeSpawn()
    ps = FakePs()
    return dispatcher.Sessions(tmp_path, git, spawn, ps, FakeKillpg(ps)), spawn


def fakes(runner: dispatcher.Sessions) -> tuple[FakePs, FakeKillpg]:
    """The fake `ps` and `killpg` a runner from `sessions` reads and signals through."""
    assert isinstance(runner.ps, FakePs)
    assert isinstance(runner.killpg, FakeKillpg)
    return runner.ps, runner.killpg


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


def test_a_followed_sessions_reason_says_its_exit_code_is_unknown(tmp_path: Path) -> None:
    """KTD2: no one knows a followed session's exit code; never `None` or `-1`."""
    runner, _ = sessions(tmp_path, FakeGit())
    pid = runner.start(74).process.pid
    record = runner.records()[74]
    assert record is not None
    fakes(runner)[0].starts[pid] = None
    reason = runner.ending(runner.follow(record)).reason
    assert reason == "the session ended with no final result; its exit code is unknown"


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
AT_LIMIT = (INIT, rejected(int(at(20, 30))), result("API Error"))
UNKNOWN = (INIT, result("You've hit your session limit · resets 8:30pm (America/Sao_Paulo)"))
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
    assert runner.ending(running) == dispatcher.Ending(
        "API Error", Marker(SESSION, "issue-70", 1759350600),
        dispatcher.Progress(marks("done", "done", "done", "current"), "Reviewing."),
        final=True, conversation=SESSION)


def test_the_conversation_is_this_attempts_else_the_marker_it_resumed_from(
        tmp_path: Path) -> None:
    """KTD5: never an earlier attempt's, which may be another worktree's conversation."""
    runner, _ = sessions(tmp_path, FakeGit())
    running = slice_of(tmp_path, INIT, event("assistant", OTHER, message={}),
                       before=(event("system", "0" * 8 + SESSION[8:]),))
    assert runner.ending(running).conversation == OTHER
    assert not runner.ending(running).final
    earlier = slice_of(tmp_path, before=(INIT, result("Stopped: blocked")))
    assert runner.ending(earlier).conversation is None
    assert not runner.ending(earlier).final
    resumed = dataclasses.replace(earlier, resumed=cause(70, LIMIT, OTHER))
    assert runner.ending(resumed).conversation == OTHER


# The status comment

NOW = at(10, 47)
UPDATED = f"Updated {dispatcher.local_time(NOW)}"


def stamp_of(stages: tuple[str, ...]) -> str:
    """The hidden status marker these marks make."""
    return f'<!-- dispatcher-status {json.dumps({"stages": list(stages)})} -->'


def test_a_running_status_shows_the_checklist_the_latest_sentence_and_its_minutes() -> None:
    """AE2: plan and plan review done, implementation current, 42 minutes in."""
    status = dispatcher.Status(dispatcher.RUNNING, marks("done", "done", "current"),
                               latest=AE2_SENTENCE, started=at(10, 5))
    assert status.body(NOW) == "\n".join((
        "**Dispatcher status: implementation** (running 42 min)", "",
        "✅ Plan", "✅ Plan review", "⏳ Implementation", "⬜ Code review", "⬜ Pull request",
        "⬜ CI", "", "Latest:", "```text", AE2_SENTENCE, "```", "", UPDATED,
        stamp_of(marks("done", "done", "current"))))


def test_the_running_time_is_whole_minutes_since_the_start() -> None:
    """KTD7: 59 seconds are no minute yet."""
    status = dispatcher.Status(dispatcher.RUNNING, marks("current"), started=at(10, 46, 1))
    assert status.body(NOW).startswith("**Dispatcher status: plan** (running 0 min)\n")
    later = dataclasses.replace(status, started=at(9, 0))
    assert later.body(NOW).startswith("**Dispatcher status: plan** (running 107 min)\n")


def test_a_running_status_without_a_sentence_has_no_latest_block() -> None:
    body = dispatcher.Status(dispatcher.RUNNING, marks("current"), started=NOW).body(NOW)
    assert "Latest:" not in body and "```" not in body


def test_a_latest_sentence_with_backticks_sits_in_a_longer_fence() -> None:
    """KTD4: nothing of the session's words renders as Markdown, mentions included."""
    sentence = "Ran ```` `uv run pytest` ```` then pinged @someone about #12 ``` done"
    body = dispatcher.Status(dispatcher.RUNNING, marks("current"), latest=sentence,
                             started=NOW).body(NOW)
    assert "Latest:\n`````text\n" + sentence + "\n`````\n" in body
    assert body.count(sentence) == 1


def test_a_short_backtick_run_keeps_the_three_backtick_fence() -> None:
    body = dispatcher.Status(dispatcher.RUNNING, marks("current"), latest="Ran `uv run pytest`.",
                             started=NOW).body(NOW)
    assert "Latest:\n```text\nRan `uv run pytest`.\n```\n" in body


def test_a_queued_status_says_why_it_waits_with_no_checklist() -> None:
    """AE1: blocked by 2 open issues, then by 1."""
    body = dispatcher.Status(dispatcher.QUEUED, reason=dispatcher.waiting(blocked=2)).body(NOW)
    assert body == "\n".join(("**Dispatcher status: queued**", "", "Blocked by 2 open issues.",
                              "", UPDATED, stamp_of(marks())))
    assert "Blocked by 1 open issue.\n" in dispatcher.Status(
        dispatcher.QUEUED, reason=dispatcher.waiting(blocked=1)).body(NOW)


def test_why_a_queued_issue_waits() -> None:
    """R3: its blockers first, then the usage limit's reset, else a free session."""
    assert dispatcher.waiting() == "waiting for a free session"
    assert dispatcher.waiting(blocked=2, held=True, until=at(20, 31)) == (
        "blocked by 2 open issues")
    assert dispatcher.waiting(held=True, until=at(20, 31)) == (
        f"waiting for the Claude usage limit to reset at {dispatcher.local_time(at(20, 31))}")
    assert dispatcher.waiting(held=True) == (
        "waiting for the Claude usage limit to reset at an unknown time")


def test_the_same_status_at_two_times_is_the_same_text() -> None:
    """KTD6: only the Updated line differs; a changed reason is a change."""
    status = dispatcher.Status(dispatcher.QUEUED, reason=dispatcher.waiting(blocked=2))
    assert status.body(NOW) != status.body(NOW + 3600)
    assert dispatcher.same_status(status.body(NOW), status.body(NOW + 3600))
    other = dispatcher.Status(dispatcher.QUEUED, reason=dispatcher.waiting(blocked=1))
    assert not dispatcher.same_status(status.body(NOW), other.body(NOW))


def test_a_sentence_starting_like_the_updated_line_still_counts() -> None:
    """Only the line above the marker is the stamp, never the session's words."""
    first = dispatcher.Status(dispatcher.RUNNING, marks("current"), latest="Updated the plan.",
                              started=NOW)
    second = dataclasses.replace(first, latest="Updated the tests.")
    assert not dispatcher.same_status(first.body(NOW), second.body(NOW))


def test_ending_with_a_pull_request_marks_it_done_and_ci_current() -> None:
    """AE6: implementation done, code review never entered, pull request done, CI current."""
    assert dispatcher.marks_opened(marks("done", "done", "current")) == (
        "done", "done", "done", "skipped", "done", "current")
    after_ci = ("skipped", "skipped", "done", "done", "done", "current")
    assert dispatcher.marks_opened(after_ci) == after_ci


def test_checks_passing_marks_ci_done() -> None:
    """AE6: ready to merge."""
    assert dispatcher.marks_passed(("done", "done", "done", "skipped", "done", "current")) == (
        "done", "done", "done", "skipped", "done", "done")


def test_stopping_fails_the_current_stage() -> None:
    """AE4: Ctrl-C during implementation; with no stage entered, the plan fails."""
    assert dispatcher.marks_stopped(marks("done", "done", "current")) == marks(
        "done", "done", "failed")
    assert dispatcher.marks_stopped(marks()) == marks("failed")


def test_stopping_a_paused_checklist_fails_the_paused_stage_not_the_plan() -> None:
    assert dispatcher.marks_stopped(marks("done", "done", "paused")) == marks(
        "done", "done", "failed")


def test_pausing_and_resuming_keep_the_stage() -> None:
    """AE7: paused in implementation, then current again."""
    assert dispatcher.marks_paused(marks("done", "done", "current")) == marks(
        "done", "done", "paused")
    assert dispatcher.marks_resumed(marks("done", "done", "paused")) == marks(
        "done", "done", "current")


def test_a_paused_status_keeps_the_checklist_and_says_when_the_limit_resets() -> None:
    """AE7: implementation paused, the reset at 20:30; no running time, no sentence."""
    status = dispatcher.Status(PAUSED, marks("done", "done", "paused"), latest=AE2_SENTENCE,
                               started=at(10, 5), reset=at(20, 30))
    assert status.body(NOW) == "\n".join((
        "**Dispatcher status: paused**", "",
        "✅ Plan", "✅ Plan review", "⏸️ Implementation", "⬜ Code review", "⬜ Pull request",
        "⬜ CI", "", "The Claude usage limit stopped the session. It resets at "
        f"{dispatcher.local_time(at(20, 30))}.", "", UPDATED,
        stamp_of(marks("done", "done", "paused"))))


def test_a_paused_status_with_an_unknown_reset_says_so() -> None:
    body = dispatcher.Status(PAUSED, marks("done", "done", "paused")).body(NOW)
    assert ("The Claude usage limit stopped the session. Its reset time is unknown.\n"
            in body)


@pytest.mark.parametrize("kind, says", [
    (INTERRUPTED, "The session was interrupted (found gone when the dispatcher started)."),
    (STOPPED, "The session was stopped with `dispatcher.py stop`.")])
def test_a_paused_status_says_its_cause_and_shows_no_reset(kind: str, says: str) -> None:
    """KTD9: only the usage limit has a reset to show."""
    body = dispatcher.Status(PAUSED, marks("done", "done", "paused"), reset=at(20, 30),
                             cause=kind).body(NOW)
    assert f"\n\n{says}\n\n" in body
    assert "reset" not in body
    assert "usage limit" not in body


@pytest.mark.parametrize("state, stages", [
    (IN_REVIEW, ("done", "done", "done", "skipped", "done", "current")),
    (READY_TO_MERGE, ("done", "done", "done", "skipped", "done", "done")),
    (NEEDS_ATTENTION, marks("done", "done", "failed")),
])
def test_an_ended_status_shows_the_checklist_without_time_or_sentence(
        state: str, stages: tuple[str, ...]) -> None:
    """R8, R9: the checklist frozen as it ended."""
    status = dispatcher.Status(state, stages, latest=AE2_SENTENCE, started=at(10, 5))
    lines = [f"{dispatcher.MARK_SIGNS[mark]} {name[0].upper()}{name[1:]}"
             for mark, name in zip(stages, dispatcher.STAGES, strict=True)]
    assert status.body(NOW) == "\n".join((f"**Dispatcher status: {state}**", "", *lines, "",
                                          UPDATED, stamp_of(stages)))
    assert "❌ Implementation" in dispatcher.Status(
        NEEDS_ATTENTION, marks("done", "done", "failed")).body(NOW)


@pytest.mark.parametrize("status", [
    dispatcher.Status(dispatcher.QUEUED, reason="waiting for a free session"),
    dispatcher.Status(dispatcher.RUNNING, marks("done", "done", "current"), latest="Working.",
                      started=0.0),
    dispatcher.Status(IN_REVIEW, ("done", "done", "done", "skipped", "done", "current")),
    dispatcher.Status(READY_TO_MERGE, ("done", "done", "done", "skipped", "done", "done")),
    dispatcher.Status(NEEDS_ATTENTION, marks("done", "failed")),
    dispatcher.Status(PAUSED, marks("done", "done", "paused"), reset=None),
], ids=lambda status: status.state)
def test_every_status_marker_reads_back_its_marks(status: dispatcher.Status) -> None:
    """KTD2: the marker is the body's last line and holds the marks, and only them."""
    body = status.body(NOW)
    assert body.splitlines()[-1] == stamp_of(status.marks)
    assert dispatcher.status_marks(body) == status.marks


@pytest.mark.parametrize("body", [
    "Dispatcher: pull request https://github.com/o/r/pull/101 is open.",
    "",
    stamp_of(marks("done", "started")),
    stamp_of((*marks(), "pending")),
    stamp_of(("done", "done")),
    '<!-- dispatcher-status {"stages": ["done", "done", -->',
    '<!-- dispatcher-status {"stages": "done"} -->',
    '<!-- dispatcher-status {"marks": ["pending", "pending", "pending", "pending", "pending", '
    '"pending"]} -->',
    stamp_of(marks()) + "\n\nA later line.",
    f'<!-- dispatcher-pause {{"session": "{SESSION}", "branch": "issue-70", "reset": null}} -->',
], ids=["no marker", "empty", "unknown mark", "seven stages", "two stages", "invalid json",
        "not a list", "no stages", "not the last line", "the pause marker"])
def test_an_unreadable_status_marker_reads_as_none(body: str) -> None:
    assert dispatcher.status_marks(body) is None


# The status comment on GitHub

COMMENTS = "repos/{owner}/{repo}/issues/74/comments"
LIST_COMMENTS = ["api", "--paginate", "--slurp", COMMENTS]
QUEUED_2 = dispatcher.Status(dispatcher.QUEUED, reason=dispatcher.waiting(blocked=2))
QUEUED_1 = dispatcher.Status(dispatcher.QUEUED, reason=dispatcher.waiting(blocked=1))
OPENED = dispatcher.Status(IN_REVIEW, ("done", "done", "done", "skipped", "done", "current"))


def rest_comment(login: str, number: int, body: str) -> dict[str, object]:
    """A comment as the REST issue-comments list gives it."""
    return {"id": number, "user": {"login": login}, "body": body,
            "created_at": "2026-10-01T15:10:00Z"}


def pages_reply(*pages: list[dict[str, object]]) -> tuple[tuple[str, ...], int, str]:
    """`gh api --paginate --slurp`'s reply: an array of pages, each an array of comments."""
    return ("api", "--paginate", "--slurp"), 0, json.dumps(list(pages))


def posted_reply(number: int) -> tuple[tuple[str, ...], int, str]:
    return ("api", "--method", "POST"), 0, json.dumps({"id": number, "body": "…"})


def writes(fake: FakeGh) -> list[list[str]]:
    """The status comments `gh` was asked to create or edit."""
    return [call for call in fake.calls if call[:2] == ["api", "--method"]]


def lists(fake: FakeGh) -> list[list[str]]:
    return [call for call in fake.calls if call[:3] == ["api", "--paginate", "--slurp"]]


def test_the_status_comment_is_the_users_newest_one_with_a_status_marker() -> None:
    """KTD1: every page counts; a stranger's marker and the user's other comments don't."""
    own = QUEUED_2.body(NOW)
    newer = OPENED.body(NOW)
    gh, fake = github(pages_reply(
        [rest_comment("me", 11, own), rest_comment("me", 12, "Dispatcher: pull request open.")],
        [rest_comment("me", 13, newer), rest_comment("stranger", 14, QUEUED_1.body(NOW))]))
    assert gh.status_comment(74) == (13, newer)
    assert fake.calls[-1] == LIST_COMMENTS


def test_an_issue_without_the_users_status_marker_has_no_status_comment() -> None:
    gh, _ = github(pages_reply([rest_comment("stranger", 14, QUEUED_1.body(NOW)),
                                rest_comment("me", 12, "Looking into it.")]))
    assert gh.status_comment(74) is None


def test_a_status_comment_is_posted_and_edited_with_its_body_as_a_field() -> None:
    """The body goes as one `-f` argument, never through a shell."""
    body = "**Dispatcher status: queued**\n\n`$(rm -rf ~)` {owner}\n\n" + stamp_of(marks())
    gh, fake = github(posted_reply(9001))
    assert gh.post_status(74, body) == 9001
    gh.edit_status(9001, body)
    assert fake.calls == [["api", "--method", "POST", COMMENTS, "-f", f"body={body}"],
                          ["api", "--method", "PATCH", "repos/{owner}/{repo}/issues/comments/9001",
                           "-f", f"body={body}"]]


def test_a_queued_issue_gets_one_comment_edited_only_when_its_text_changes() -> None:
    """AE1: posted at the first poll, untouched at the next, edited by id once a blocker closes."""
    gh, fake = github(pages_reply([]), posted_reply(9001))
    board = dispatcher.Board(gh)
    board.report(74, QUEUED_2, NOW, create=True)
    assert writes(fake) == [["api", "--method", "POST", COMMENTS, "-f",
                             f"body={QUEUED_2.body(NOW)}"]]
    calls = len(fake.calls)
    board.report(74, QUEUED_2, NOW + 300, create=True)
    assert len(fake.calls) == calls
    board.report(74, QUEUED_1, NOW + 600, create=True)
    assert writes(fake)[1:] == [["api", "--method", "PATCH",
                                 "repos/{owner}/{repo}/issues/comments/9001", "-f",
                                 f"body={QUEUED_1.body(NOW + 600)}"]]
    assert lists(fake) == [LIST_COMMENTS]


def test_after_a_restart_the_comment_is_found_by_its_marker_and_edited() -> None:
    """AE5: no second status comment."""
    running = dispatcher.Status(dispatcher.RUNNING, marks("done", "done", "current"),
                                started=NOW - 600)
    gh, fake = github(pages_reply([rest_comment("me", 9001, running.body(NOW - 300))]))
    board = dispatcher.Board(gh)
    assert board.marks(74) == marks("done", "done", "current")
    board.report(74, OPENED, NOW, create=False)
    assert writes(fake) == [["api", "--method", "PATCH",
                             "repos/{owner}/{repo}/issues/comments/9001", "-f",
                             f"body={OPENED.body(NOW)}"]]
    assert lists(fake) == [LIST_COMMENTS]


def test_an_issue_without_a_status_comment_gets_none_where_it_may_not_be_created() -> None:
    """AE8, R12: #60 was in review before the feature; it is listed once, never written."""
    gh, fake = github(pages_reply([]))
    board = dispatcher.Board(gh)
    board.report(60, OPENED, NOW, create=False)
    board.report(60, OPENED, NOW + 300, create=False)
    assert board.marks(60) is None
    assert writes(fake) == []
    assert lists(fake) == [["api", "--paginate", "--slurp",
                            "repos/{owner}/{repo}/issues/60/comments"]]


def test_the_newest_of_the_users_status_comments_is_edited_never_a_strangers() -> None:
    gh, fake = github(pages_reply([rest_comment("me", 11, QUEUED_2.body(NOW)),
                                   rest_comment("me", 13, QUEUED_2.body(NOW)),
                                   rest_comment("stranger", 14, QUEUED_2.body(NOW))]))
    dispatcher.Board(gh).report(74, QUEUED_1, NOW, create=True)
    assert [call[3] for call in writes(fake)] == ["repos/{owner}/{repo}/issues/comments/13"]


def test_a_failing_list_raises_with_its_stderr_and_the_next_report_lists_again() -> None:
    gh, fake = github((("api", "--paginate"), 1, ""))
    board = dispatcher.Board(gh)
    with pytest.raises(dispatcher.GhError, match="something broke"):
        board.report(74, QUEUED_2, NOW, create=True)
    assert writes(fake) == []
    fake.script = [pages_reply([]), posted_reply(9001)]
    board.report(74, QUEUED_2, NOW, create=True)
    assert len(lists(fake)) == 2
    assert [call[2] for call in writes(fake)] == ["POST"]


def test_a_failing_create_raises_with_its_stderr_and_the_next_report_tries_again() -> None:
    """A create whose reply was lost may have landed: the next report lists before posting."""
    gh, fake = github(pages_reply([]), (("api", "--method", "POST"), 1, ""))
    board = dispatcher.Board(gh)
    with pytest.raises(dispatcher.GhError, match="something broke"):
        board.report(74, QUEUED_2, NOW, create=True)
    fake.script = [pages_reply([]), posted_reply(9001)]
    board.report(74, QUEUED_2, NOW, create=True)
    assert len(lists(fake)) == 2
    assert [call[2] for call in writes(fake)] == ["POST", "POST"]
    board.report(74, QUEUED_1, NOW, create=True)
    assert writes(fake)[-1][3] == "repos/{owner}/{repo}/issues/comments/9001"


@pytest.mark.parametrize("out", [
    "[{\"id\": 1}][{\"id\": 2}]",
    "",
    json.dumps({"message": "Not Found"}),
    json.dumps([{"id": 13}]),
    json.dumps([[{"user": {"login": "me"}, "body": stamp_of(marks())}]]),
    json.dumps([[{"id": "13", "user": {"login": "me"}, "body": stamp_of(marks())}]]),
], ids=["concatenated pages", "empty", "an object", "a page not an array", "no id",
        "an id not a number"])
def test_an_unreadable_comment_list_raises(out: str) -> None:
    """KTD5: only a GhError is caught where the board is used."""
    gh, fake = github((("api", "--paginate"), 0, out))
    board = dispatcher.Board(gh)
    with pytest.raises(dispatcher.GhError):
        board.report(74, QUEUED_2, NOW, create=True)
    assert writes(fake) == []


@pytest.mark.parametrize("out", ["", json.dumps({"message": "ok"}), json.dumps({"id": None})],
                         ids=["empty", "no id", "a null id"])
def test_an_unreadable_create_reply_raises(out: str) -> None:
    gh, _ = github((("api", "--method", "POST"), 0, out))
    with pytest.raises(dispatcher.GhError):
        gh.post_status(74, QUEUED_2.body(NOW))


def test_a_failed_edit_forgets_the_comment_so_the_next_report_lists_again() -> None:
    """The author deleted the comment: the edit by its cached id fails, then none is found."""
    gh, fake = github(pages_reply([rest_comment("me", 9001, QUEUED_2.body(NOW))]),
                      (("api", "--method", "PATCH"), 1, ""))
    board = dispatcher.Board(gh)
    with pytest.raises(dispatcher.GhError, match="something broke"):
        board.report(74, QUEUED_1, NOW, create=True)
    fake.script = [pages_reply([])]
    board.report(74, OPENED, NOW, create=False)
    assert len(lists(fake)) == 2
    assert [call[2] for call in writes(fake)] == ["PATCH"]


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


@pytest.mark.parametrize("kind, says", [(INTERRUPTED, "was interrupted"),
                                        (STOPPED, "was stopped with `dispatcher.py stop`")])
def test_a_resume_after_an_interruption_or_a_stop_says_why(tmp_path: Path, kind: str,
                                                          says: str) -> None:
    """R8, KTD4: told why it stopped, never that a limit reset; `Closes #N` all the same."""
    (tmp_path / ".claude/worktrees/issue-70").mkdir(parents=True)
    runner, spawn = sessions(tmp_path, FakeGit())
    runner.resume(70, cause(70, kind))
    (args, _), = spawn.calls
    assert args[:4] == ["claude", "-p", "--resume", SESSION]
    prompt = args[4]
    assert says in prompt
    assert "usage limit" not in prompt
    assert "reset" not in prompt
    assert "Continue `/compound-engineering:lfg #70` where it stopped." in prompt
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


# Session records

def record_file(tmp_path: Path, issue: int) -> Path:
    return tmp_path / dispatcher.STATE / f"sessions/issue-{issue}.json"


def test_a_started_session_writes_its_record(tmp_path: Path) -> None:
    """KTD1: what a later dispatcher needs to follow it, renamed into place whole."""
    runner, _ = sessions(tmp_path, FakeGit())
    running = runner.start(74)
    assert json.loads(record_file(tmp_path, 74).read_text()) == {
        "issue": 74, "pid": running.process.pid, "start": START, "branch": "issue-74",
        "worktree": str(tmp_path / ".claude/worktrees/issue-74"),
        "log": str(tmp_path / dispatcher.STATE / "logs/issue-74.log"), "since": 0,
        "started": running.started, "resumed": None, "start_marks": list(dispatcher.UNSTARTED),
        "stopped": False}
    assert [path.name for path in record_file(tmp_path, 74).parent.iterdir()] == [
        "issue-74.json"]


def test_a_resumed_session_records_its_marker_and_the_marks_it_continues_from(
        tmp_path: Path) -> None:
    (tmp_path / ".claude/worktrees/issue-70-2").mkdir(parents=True)
    runner, _ = sessions(tmp_path, FakeGit())
    marker = Marker(SESSION, "issue-70-2", 1759350600)
    resumed = marks("done", "done", "current")
    running = runner.resume(70, marker, resumed)
    assert running.start_marks == resumed
    record = json.loads(record_file(tmp_path, 70).read_text())
    assert record["resumed"] == {"session": SESSION, "branch": "issue-70-2", "reset": 1759350600,
                                 "cause": "limit"}
    assert record["start_marks"] == list(resumed)
    assert (record["branch"], record["pid"]) == ("issue-70-2", running.process.pid)


def test_a_record_keeps_the_cause_its_session_resumed_from(tmp_path: Path) -> None:
    """KTD4: a later dispatcher judges a resumed session against the marker of the same cause."""
    (tmp_path / ".claude/worktrees/issue-70").mkdir(parents=True)
    runner, _ = sessions(tmp_path, FakeGit())
    runner.resume(70, cause(70, STOPPED))
    record = runner.records()[70]
    assert record is not None
    assert record.resumed == cause(70, STOPPED)


def test_a_record_round_trips_into_a_running_session(tmp_path: Path) -> None:
    """R3: an earlier dispatcher's session, followed by PID while `ps` gives its start time."""
    (tmp_path / ".claude/worktrees/issue-70").mkdir(parents=True)
    runner, _ = sessions(tmp_path, FakeGit())
    started = runner.resume(70, limit(70), marks("done", "current"))
    record = runner.records()[70]
    assert record is not None
    followed = runner.follow(record)
    assert dataclasses.replace(followed, process=started.process) == started
    assert followed.process.pid == started.process.pid
    assert followed.process.poll() is None
    assert followed.process.returncode is None


def test_the_same_pid_with_another_start_time_is_not_the_session(tmp_path: Path) -> None:
    """R6: a process that merely reuses the PID."""
    runner, _ = sessions(tmp_path, FakeGit())
    pid = runner.start(74).process.pid
    record = runner.records()[74]
    assert record is not None
    ps, _ = fakes(runner)
    ps.starts[pid] = "Thu Oct  1 19:42:07 2026"
    process = runner.follow(record).process
    assert process.poll() is not None
    assert process.returncode is None


def test_a_dead_pid_is_not_running_and_its_exit_code_stays_unknown(tmp_path: Path) -> None:
    runner, _ = sessions(tmp_path, FakeGit())
    pid = runner.start(74).process.pid
    record = runner.records()[74]
    assert record is not None
    ps, _ = fakes(runner)
    ps.starts[pid] = None
    process = runner.follow(record).process
    assert process.poll() is not None
    assert process.returncode is None


def test_a_followed_session_is_signalled_through_its_process_group(tmp_path: Path) -> None:
    """KTD2: the tools the session spawned end with it; `end` works on it unchanged."""
    runner, _ = sessions(tmp_path, FakeGit())
    pid = runner.start(74).process.pid
    record = runner.records()[74]
    assert record is not None
    ps, killpg = fakes(runner)
    followed = runner.follow(record)
    runner.end([followed])
    assert killpg.calls == [(pid, signal.SIGTERM)]
    assert followed.process.poll() is not None
    followed.process.terminate()
    followed.process.kill()
    assert killpg.calls == [(pid, signal.SIGTERM)]  # a group gone is never signalled again
    ps.starts[pid] = START
    killpg.stubborn = True
    followed.process.terminate()
    with pytest.raises(subprocess.TimeoutExpired):
        followed.process.wait(0)
    followed.process.kill()
    assert killpg.calls == [(pid, signal.SIGTERM), (pid, signal.SIGTERM), (pid, signal.SIGKILL)]
    assert followed.process.wait(0) is not None


def test_a_record_is_marked_stopped_and_removed(tmp_path: Path) -> None:
    runner, _ = sessions(tmp_path, FakeGit())
    runner.start(74)
    runner.start(75)
    record = runner.records()[74]
    assert record is not None
    assert runner.mark_stopped(record) == dataclasses.replace(record, stopped=True)
    assert runner.records() == {74: dataclasses.replace(record, stopped=True),
                                75: runner.records()[75]}
    assert json.loads(record_file(tmp_path, 74).read_text())["stopped"] is True
    runner.forget(74)
    runner.forget(74)
    assert list(runner.records()) == [75]


@pytest.mark.parametrize("text", ["{", "[]", '{"issue": 74}',
                                  '{"issue": 74, "pid": 0, "start": null, "branch": "issue-74", '
                                  '"worktree": "/w", "log": "/l", "since": 0, "started": 0, '
                                  '"resumed": null, "start_marks": [], "stopped": false}'])
def test_an_unreadable_record_reads_as_none(tmp_path: Path, text: str) -> None:
    """A record damaged from outside is no record, never a PID to signal (0 is our own group)."""
    runner, _ = sessions(tmp_path, FakeGit())
    record_file(tmp_path, 74).parent.mkdir(parents=True)
    record_file(tmp_path, 74).write_text(text)
    assert runner.records() == {74: None}


def test_the_start_time_is_read_in_utc_and_the_c_locale(tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """KTD2: `lstart` follows the reader's zone and locale; both readings pin them."""
    calls: list[tuple[list[str], dict[str, str]]] = []

    def run(args: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        calls.append((args, options["env"]))
        return subprocess.CompletedProcess(args, 0, START + "\n", "")

    monkeypatch.setattr(subprocess, "run", run)
    spawn = FakeSpawn()
    runner = dispatcher.Sessions(tmp_path, FakeGit(), spawn, killpg=FakeKillpg(FakePs()))
    pid = runner.start(74).process.pid
    record = runner.records()[74]
    assert record is not None
    assert record.start == START
    assert runner.follow(record).process.poll() is None
    assert [args for args, _ in calls] == [["ps", "-o", "lstart=", "-p", str(pid)]] * 2
    assert all((env["TZ"], env["LC_ALL"]) == ("UTC", "C") for _, env in calls)


def test_a_session_whose_start_time_cannot_be_read_still_has_its_record(tmp_path: Path) -> None:
    """It exited at once: its record never matches a process, so a later dispatcher judges it."""
    runner, _ = sessions(tmp_path, FakeGit())
    ps, _ = fakes(runner)
    ps.default = None
    runner.start(74)
    ps.default = START
    record = runner.records()[74]
    assert record is not None
    assert record.start is None
    assert runner.follow(record).process.poll() is not None


# The command

@dataclasses.dataclass(frozen=True)
class Wrote:
    """A status comment `gh` wrote: posted, else edited."""

    issue: int
    posted: bool
    body: str


class FakeGitHub:
    """The gateway's interface over fixed answers; records the writes, status comments included.

    An issue's status comment has the id 9000 + its number.
    """

    def __init__(self, issues: dict[str, list[tuple[Issue, tuple[PullRequest, ...]]]] | None = None,
                 *, head: dict[str, tuple[PullRequest, ...]] | None = None,
                 linked: frozenset[int] = frozenset(), passing: bool = False,
                 broken: int | None = None, markers: dict[int, Marker] | None = None,
                 comments: dict[int, str] | None = None) -> None:
        self.answers = issues or {}
        self.records = markers or {}  # each paused issue's valid marker, as its comments hold it
        self.comments = {issue: (9000 + issue, body) for issue, body in (comments or {}).items()}
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
        """The issues with this label; `issues <label>` in `flaky` fails it once."""
        self._flake(f"issues {label}")
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

    def status_comment(self, issue: int) -> tuple[int, str] | None:
        """The issue's status comment; `list #N` or `status #N` in `flaky` fails it once."""
        self._flake(f"list #{issue}")
        self._flake(f"status #{issue}")
        return self.comments.get(issue)

    def post_status(self, issue: int, body: str) -> int:
        """Post the issue's status comment; `status #N` in `flaky` fails it once."""
        self._flake(f"status #{issue}")
        self.comments[issue] = (9000 + issue, body)
        self.writes.append(Wrote(issue, True, body))
        return 9000 + issue

    def edit_status(self, comment: int, body: str) -> None:
        """Edit a status comment; `status #N` in `flaky` fails it once."""
        issue = comment - 9000
        self._flake(f"status #{issue}")
        self.comments[issue] = (comment, body)
        self.writes.append(Wrote(issue, False, body))


def moves(gh: FakeGitHub) -> list[tuple[int, tuple[str, ...]]]:
    return [(write.issue, write.add) for write in gh.writes if isinstance(write, Move)]


def last_move(gh: FakeGitHub) -> Move:
    """The last label move written."""
    return [write for write in gh.writes if isinstance(write, Move)][-1]


def state_of(body: str) -> str:
    """The state a status comment shows: `running` for a stage's running header."""
    header = body.splitlines()[0]
    if "(running " in header:
        return dispatcher.RUNNING
    return header.removeprefix("**Dispatcher status: ").removesuffix("**")


def trail(gh: FakeGitHub) -> list[tuple[int, object]]:
    """In order, the labels each move added and the state each status comment was written with."""
    return [(write.issue, write.add) if isinstance(write, Move)
            else (write.issue, state_of(write.body))
            for write in gh.writes if isinstance(write, Move | Wrote)]


def shown(gh: FakeGitHub, issue: int) -> list[tuple[str, tuple[str, ...] | None]]:
    """The states and marks the issue's status comment was written with, in order."""
    return [(state_of(write.body), dispatcher.status_marks(write.body)) for write in gh.writes
            if isinstance(write, Wrote) and write.issue == issue]


@pytest.mark.parametrize("argv", [["dispatcher.py"], ["dispatcher.py", "start"]])
def test_misuse_prints_the_usage(capsys: pytest.CaptureFixture[str], argv: list[str]) -> None:
    assert dispatcher.main(argv) == 2
    out = capsys.readouterr().out
    assert "python3 tools/dispatcher/dispatcher.py run" in out
    assert "python3 tools/dispatcher/dispatcher.py stop" in out


@pytest.fixture
def locks() -> Iterator[list[int]]:
    """The lock descriptors a test holds, closed after it: closing releases the flock."""
    held: list[int] = []
    yield held
    for descriptor in held:
        with contextlib.suppress(OSError):
            os.close(descriptor)


def hold(lock: Path, locks: list[int], pid: int | None = None) -> int:
    """Hold the lock as another process would (an open file description of its own), its PID
    `pid` written inside, if given."""
    descriptor = dispatcher.take(lock)
    assert descriptor is not None
    locks.append(descriptor)
    if pid is not None:
        os.ftruncate(descriptor, 0)
        os.pwrite(descriptor, str(pid).encode(), 0)
    return descriptor


def test_a_second_dispatcher_refuses_to_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                              capsys: pytest.CaptureFixture[str],
                                              locks: list[int]) -> None:
    """KTD6: it says the holder's PID, which its refusal leaves as it was."""
    lock = tmp_path / dispatcher.STATE / "lock"
    hold(lock, locks, 4242)
    monkeypatch.setattr(dispatcher, "ROOT", tmp_path)
    monkeypatch.setattr(dispatcher, "GitHub", lambda: pytest.fail("no gh call when refusing"))
    assert dispatcher.main(["dispatcher.py", "run"]) == 1
    assert "(PID 4242)" in capsys.readouterr().out
    assert lock.read_text() == "4242"


def test_a_lock_file_left_by_a_dead_process_does_not_block(tmp_path: Path,
                                                           locks: list[int]) -> None:
    """KTD6: the kernel dropped its flock; only a live holder refuses the next."""
    lock = tmp_path / "lock"
    lock.write_text("999999")
    descriptor = dispatcher.take(lock)
    assert descriptor is not None
    locks.append(descriptor)
    assert lock.read_text() == str(os.getpid())
    assert dispatcher.take(lock) is None
    assert lock.read_text() == str(os.getpid())


def test_the_lock_is_not_inherited_by_the_sessions(tmp_path: Path, locks: list[int]) -> None:
    """A session outliving its dispatcher must not keep the lock: `stop` waits for it."""
    descriptor = dispatcher.take(tmp_path / "lock")
    assert descriptor is not None
    locks.append(descriptor)
    assert not os.get_inheritable(descriptor)


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
    assert "Worktree: `.claude/worktrees/issue-74`" in (move.comment or "")
    assert str(tmp_path) not in (move.comment or "")


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
    assert "no space" in (last_move(gh).comment or "")
    assert boss.running == {}


def test_a_session_that_cannot_start_names_its_worktree_inside_the_checkout(
        tmp_path: Path) -> None:
    """KTD8: git's error names the worktree; the comment names it from the checkout."""
    gh = FakeGitHub({READY: [(ready(70), ())]})
    git = FakeGit(fail="worktree add",
                  stderr=f"fatal: '{tmp_path}/.claude/worktrees/issue-70' already exists")
    runner, _ = sessions(tmp_path, git)
    dispatcher.Dispatcher(gh, runner, 1, say=lambda line: None).poll()
    comment = last_move(gh).comment or ""
    assert "could not start: fatal: '.claude/worktrees/issue-70' already exists" in comment
    assert str(tmp_path) not in comment


def test_stopping_leaves_a_live_session_running(tmp_path: Path) -> None:
    """AE1, R1, R2, KTD9: Ctrl-C mid-implementation ends the dispatcher only.

    The session is not signalled, #74 stays in progress with no comment, its status comment
    is not edited though its log moved on, and its record stays for the next start.
    """
    gh = FakeGitHub({READY: [(ready(74), ())]})
    lines: list[str] = []
    boss, _ = boss_at(tmp_path, gh, 1, Clock(at(15)), lines)
    boss.poll()
    gh.answers = {}
    process = boss.running[74].process
    assert isinstance(process, FakeProcess)
    logs(boss, 74, *AE2_EVENTS)
    written = list(gh.writes)
    record = record_file(tmp_path, 74).read_text()
    boss.stop()
    assert process.signals == []
    assert process.returncode is None
    assert gh.writes == written
    assert moves(gh) == [(74, (IN_PROGRESS,))]
    assert lines[-1] == (f"dispatcher: #74 left running (PID {process.pid}), "
                         "the next start follows it")
    assert record_file(tmp_path, 74).read_text() == record
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


def two_sessions(tmp_path: Path, gh: FakeGitHub, *events: str
                 ) -> tuple[dispatcher.Dispatcher, FakeProcess, FakeProcess]:
    """A dispatcher whose session for #74 exited while #75's still runs.

    #74 wrote these events, then exited with code 0; stopping leaves #75 running.
    """
    runner, _ = sessions(tmp_path, FakeGit())
    boss = dispatcher.Dispatcher(gh, runner, 2, say=lambda line: None)
    gh.answers = {READY: [(ready(74), ()), (ready(75), ())]}
    boss.poll()
    gh.answers = {}
    done, live = boss.running[74].process, boss.running[75].process
    assert isinstance(done, FakeProcess)
    assert isinstance(live, FakeProcess)
    exits(boss, 74, *events)
    return boss, done, live


@pytest.mark.parametrize(("head", "events", "verdict"), [
    ((PR,), (), IN_REVIEW),
    ((), (INIT, result("Stopped: the plan returned blocked.")), NEEDS_ATTENTION),
    ((), AT_LIMIT, PAUSED)], ids=["in review", "needs attention", "paused"])
def test_stopping_judges_a_session_that_already_ended(
        tmp_path: Path, head: tuple[PullRequest, ...], events: tuple[str, ...],
        verdict: str) -> None:
    """KTD3 at stop: #74 exited before Ctrl-C and is judged as a poll would; #75 is left."""
    gh = FakeGitHub(head={"issue-74": head})
    boss, done, live = two_sessions(tmp_path, gh, *events)
    boss.stop()
    assert done.signals == []
    assert live.signals == []
    assert moves(gh)[2:] == [(74, (verdict,))]
    assert [issue for issue, _ in trail(gh)[4:]] == [74, 74]  # its move, then its status
    assert (Link(101, 74) in gh.writes) == bool(head)
    assert not record_file(tmp_path, 74).exists()
    assert record_file(tmp_path, 75).exists()
    assert boss.running == {}


def test_stopping_when_github_cannot_read_an_ended_session(tmp_path: Path) -> None:
    gh = FakeGitHub(head={"issue-74": (PR,)})
    boss, _, live = two_sessions(tmp_path, gh)
    gh.flaky = {"head"}
    boss.stop()
    assert live.signals == []
    assert moves(gh)[2:] == [(74, (NEEDS_ATTENTION,))]
    assert trail(gh)[4:] == [(74, (NEEDS_ATTENTION,)), (74, NEEDS_ATTENTION)]
    move = last_move(gh)
    assert "HTTP 502" in (move.comment or "")
    assert "Worktree: `.claude/worktrees/issue-74`" in (move.comment or "")
    assert str(tmp_path) not in (move.comment or "")


def test_a_verdict_that_fails_its_last_try_at_stop_keeps_the_record(tmp_path: Path) -> None:
    """KTD1: #74's move failed at a poll and again at stop: the next start judges it again."""
    gh = FakeGitHub(head={"issue-74": (PR,)})
    boss = ended_session(tmp_path, gh)
    gh.flaky = {"move"}
    boss.poll()
    gh.flaky = {"move"}
    boss.stop()
    assert (74, (IN_REVIEW,)) not in moves(gh)
    assert record_file(tmp_path, 74).exists()


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
    pause = last_move(gh)
    assert (pause.issue, pause.remove, pause.add, pause.comment_first) == (
        70, (IN_PROGRESS,), (PAUSED,), True)
    assert "20:30" in (pause.comment or "")
    assert (pause.comment or "").splitlines()[-1] == (
        f'<!-- dispatcher-pause {{"session": "{SESSION}", "branch": "issue-70", '
        f'"reset": {int(at(20, 30))}, "cause": "limit"}} -->')
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
    assert [write for write in gh.writes if not isinstance(write, Wrote)] == [
        Move(70, (PAUSED, READY, NEEDS_ATTENTION), (IN_PROGRESS,)),
        Move(72, (PAUSED, READY, NEEDS_ATTENTION), (IN_PROGRESS,))]
    assert trail(gh)[2:] == [(74, dispatcher.QUEUED)]
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
        f'"reset": {int(at(22))}, "cause": "limit"}} -->')


def test_a_resumed_session_at_the_limit_again_with_nothing_new_does_not_comment(
        tmp_path: Path) -> None:
    """KTD5: the same session, the reset still unknown: the labels swap, no comment."""
    boss, gh = resumed_once(tmp_path, Marker(SESSION, "issue-70", None))
    exits(boss, 70, *UNKNOWN)
    boss.poll()
    assert gh.writes[-1] == Move(70, (IN_PROGRESS,), (PAUSED,))


def test_interrupted_and_stopped_issues_resume_at_the_first_poll_without_a_hold(
        tmp_path: Path) -> None:
    """AE7, R8, R12: no usage-limit wait at start; each resumes told its own cause."""
    worktrees(tmp_path, "issue-70", "issue-72")
    gh = FakeGitHub({PAUSED: [(paused(70), ()), (paused(72), ())], READY: [(ready(74), ())]},
                    markers={70: cause(70, INTERRUPTED), 72: cause(72, STOPPED, OTHER)})
    lines: list[str] = []
    boss, spawn = boss_at(tmp_path, gh, 2, Clock(at(15)), lines)
    boss.start()
    boss.poll()
    (interrupted, _), (stopped, _) = resumes(spawn)
    assert (interrupted[3], stopped[3]) == (SESSION, OTHER)
    assert "was interrupted" in interrupted[4]
    assert "`dispatcher.py stop`" in stopped[4]
    assert not [line for line in lines if "usage limit" in line]
    assert "dispatcher: #74: waiting for a free session (2 of 2 in use)" in lines


def test_a_pause_of_another_cause_holds_no_start(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """KTD4: only the usage limit holds starts; the slot an interrupted session frees is used."""
    gh = FakeGitHub({READY: [(ready(70), ())]})
    lines: list[str] = []
    boss, spawn = boss_at(tmp_path, gh, 1, Clock(at(15)), lines)
    boss.poll()
    gh.answers = {READY: [(ready(74), ())]}
    exits(boss, 70)
    monkeypatch.setattr(boss.sessions, "ending", lambda running: dispatcher.Ending(
        "gone", cause(70, INTERRUPTED), Progress(marks("current"))))
    boss.poll()
    assert moves(gh) == [(70, (IN_PROGRESS,)), (70, (PAUSED,)), (74, (IN_PROGRESS,))]
    pause = [write for write in gh.writes if isinstance(write, Move)][1]
    assert "the session was interrupted" in (pause.comment or "")
    assert len(spawn.calls) == 2
    assert not [line for line in lines if "usage limit" in line]
    paused_body = [write.body for write in gh.writes
                   if isinstance(write, Wrote) and write.issue == 70][-1]
    assert "The session was interrupted" in paused_body


def test_comments_name_the_worktree_and_log_inside_the_checkout(tmp_path: Path) -> None:
    """AE8, R15: needing attention and paused alike; the terminal keeps the full paths."""
    gh = FakeGitHub({READY: [(ready(70), ()), (ready(72), ())]})
    lines: list[str] = []
    boss, _ = boss_at(tmp_path, gh, 2, Clock(at(15)), lines)
    boss.poll()
    gh.answers = {}
    exits(boss, 70, INIT, result("lfg stopped: no work source", error=False))
    exits(boss, 72, *AT_LIMIT)
    boss.poll()
    comments = {write.issue: write.comment or "" for write in gh.writes
                if isinstance(write, Move) and write.comment}
    assert sorted(comments) == [70, 72]
    for issue, comment in comments.items():
        assert f"Worktree: `.claude/worktrees/issue-{issue}`" in comment
        assert f"Log: `tools/dispatcher/.state/logs/issue-{issue}.log`" in comment
        assert str(tmp_path) not in comment
    log = tmp_path / dispatcher.STATE / "logs/issue-70.log"
    assert f"dispatcher: #70 session ended (exit code 0), log {log}" in lines


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
    assert [write for write in gh.writes if not isinstance(write, Wrote)] == ["labels"]


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
    assert "the worktree .claude/worktrees/issue-70 is gone" in (failure.comment or "")
    assert "Worktree: `.claude/worktrees/issue-70`" in (failure.comment or "")
    assert "Log: `tools/dispatcher/.state/logs/issue-70.log`" in (failure.comment or "")
    assert str(tmp_path) not in (failure.comment or "")
    assert spawn.calls == []
    assert boss.running == {}


def test_stopping_leaves_a_paused_issue_alone(tmp_path: Path) -> None:
    """#70 is paused on GitHub, #75 runs: stopping moves neither, and #75 is left running."""
    gh = FakeGitHub({READY: [(ready(75), ())]},
                    markers={70: Marker(SESSION, "issue-70", int(at(20, 30)))})
    boss, _ = boss_at(tmp_path, gh, 1, Clock(at(18)), [])
    boss.poll()
    gh.answers = {PAUSED: [(paused(70), ())]}
    process = boss.running[75].process
    assert isinstance(process, FakeProcess)
    boss.stop()
    assert process.signals == []
    assert moves(gh) == [(75, (IN_PROGRESS,))]


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


# Session records across the command

def test_a_verdict_applied_in_full_removes_the_record(tmp_path: Path) -> None:
    gh = FakeGitHub(head={"issue-74": (PR,)})
    boss = ended_session(tmp_path, gh)
    assert record_file(tmp_path, 74).exists()
    boss.poll()
    assert (74, (IN_REVIEW,)) in moves(gh)
    assert not record_file(tmp_path, 74).exists()


def test_a_verdict_whose_move_fails_keeps_the_record_until_its_retry(tmp_path: Path) -> None:
    """KTD1: a verdict that fails survives a restart, judged again from its record."""
    gh = FakeGitHub(head={"issue-74": (PR,)})
    boss = ended_session(tmp_path, gh)
    gh.flaky = {"move"}
    boss.poll()
    assert record_file(tmp_path, 74).exists()
    boss.poll()
    assert (74, (IN_REVIEW,)) in moves(gh)
    assert not record_file(tmp_path, 74).exists()


def test_a_status_report_that_fails_keeps_the_record_until_its_retry(tmp_path: Path) -> None:
    gh = FakeGitHub(head={"issue-74": (PR,)})
    boss = ended_session(tmp_path, gh)
    gh.flaky = {"status #74"}
    boss.poll()
    assert (74, (IN_REVIEW,)) in moves(gh)
    assert record_file(tmp_path, 74).exists()
    boss.poll()
    assert not record_file(tmp_path, 74).exists()


def test_a_new_session_keeps_its_record_when_the_last_ones_verdict_clears(tmp_path: Path) -> None:
    """#70 paused, its report failed; resumed in the same poll: the retry leaves the new record."""
    worktrees(tmp_path, "issue-70")
    gh = FakeGitHub({READY: [(ready(70), ())]}, markers={70: limit(70)})
    boss, spawn = boss_at(tmp_path, gh, 1, Clock(at(20, 35)), [])
    boss.poll()
    exits(boss, 70, *AT_LIMIT)
    gh.answers = {PAUSED: [(paused(70), ())]}
    gh.flaky = {"status #70"}
    boss.poll()
    assert [args[2] for args, _ in spawn.calls][1:] == ["--resume"]
    gh.answers = {}
    boss.poll()
    assert json.loads(record_file(tmp_path, 70).read_text())["pid"] == spawn.processes[-1].pid


@pytest.mark.parametrize("paused_one", [False, True], ids=["dispatched", "resumed"])
def test_a_record_that_cannot_be_written_ends_the_session_and_needs_attention(
        tmp_path: Path, paused_one: bool) -> None:
    """A session no later dispatcher could follow or stop must not run on."""
    record_file(tmp_path, 74).parent.parent.mkdir(parents=True)
    record_file(tmp_path, 74).parent.write_text("a file where the records go")
    worktrees(tmp_path, "issue-74")
    gh = (FakeGitHub({PAUSED: [(paused(74), ())]}, markers={74: limit(74)}) if paused_one
          else FakeGitHub({READY: [(ready(74), ())]}))
    boss, spawn = boss_at(tmp_path, gh, 1, Clock(at(20, 35)), [])
    boss.poll()
    process, = spawn.processes
    assert process.signals == ["terminate"]
    assert moves(gh) == [(74, (IN_PROGRESS,)), (74, (NEEDS_ATTENTION,))]
    comment = last_move(gh).comment or ""
    assert "could not " + ("resume" if paused_one else "start") in comment
    assert "record" in comment
    assert "tools/dispatcher/.state/sessions" in comment
    assert str(tmp_path) not in comment
    assert boss.running == {}


def test_a_resumed_sessions_record_holds_the_marks_it_continues_from(tmp_path: Path) -> None:
    """The record carries the checklist a later dispatcher reports from."""
    worktrees(tmp_path, "issue-70")
    gh = FakeGitHub({PAUSED: [(paused(70), ())]}, markers={70: limit(70)},
                    comments={70: body_of(PAUSED, marks("done", "done", "paused"))})
    boss, _ = boss_at(tmp_path, gh, 1, Clock(at(20, 35)), [])
    boss.poll()
    assert boss.running[70].start_marks == marks("done", "done", "current")
    assert json.loads(record_file(tmp_path, 70).read_text())["start_marks"] == list(
        marks("done", "done", "current"))


# The status comment at each step

AE2_EVENTS = (skill("ce-plan"), says("Planning #74."), skill("ce-doc-review"), skill("ce-work"),
              says(AE2_SENTENCE))
OPENED_MARKS = ("done", "done", "done", "skipped", "done", "current")


def body_of(state: str, stages: tuple[str, ...], **details: Any) -> str:
    """A status comment's body as an earlier run left it."""
    return dispatcher.Status(state, stages, **details).body(at(9))


def logs(boss: dispatcher.Dispatcher, issue: int, *events: dict[str, Any]) -> None:
    """The issue's running session writes these events to its part of the log."""
    with boss.running[issue].log.open("a") as log:
        log.write("".join(json.dumps(event) + "\n" for event in events))


def wrote(gh: FakeGitHub) -> list[Wrote]:
    """The status comments written, in order."""
    return [write for write in gh.writes if isinstance(write, Wrote)]


def test_a_queued_issue_says_why_it_waits_then_runs_once_picked(tmp_path: Path) -> None:
    """AE1: posted blocked by 2, untouched while nothing changes, blocked by 1, then running."""
    gh = FakeGitHub({READY: [(ready(74, blocked=2), ())]})
    boss, _ = boss_at(tmp_path, gh, 1, Clock(at(15)), [])
    boss.poll()
    boss.poll()
    gh.answers = {READY: [(ready(74, blocked=1), ())]}
    boss.poll()
    gh.answers = {READY: [(ready(74), ())]}
    boss.poll()
    assert trail(gh) == [(74, dispatcher.QUEUED), (74, dispatcher.QUEUED), (74, (IN_PROGRESS,)),
                         (74, dispatcher.RUNNING)]
    first, second, running = wrote(gh)
    assert first.posted
    assert "Blocked by 2 open issues." in first.body
    assert not second.posted
    assert "Blocked by 1 open issue." in second.body
    assert not running.posted
    assert dispatcher.status_marks(running.body) == marks("current")


def test_a_running_session_shows_its_stage_and_last_sentence(tmp_path: Path) -> None:
    """AE2: plan and plan review done, implementation current, the sentence, 42 minutes in."""
    gh = FakeGitHub({READY: [(ready(74), ())]})
    clock = Clock(at(15))
    boss, _ = boss_at(tmp_path, gh, 1, clock, [])
    boss.poll()
    gh.answers = {}
    boss.running[74] = dataclasses.replace(boss.running[74], started=at(15))
    logs(boss, 74, *AE2_EVENTS)
    clock.now = at(15, 42)
    boss.poll()
    last = wrote(gh)[-1]
    assert not last.posted
    assert last.body.startswith("**Dispatcher status: implementation** (running 42 min)\n")
    assert f"Latest:\n```text\n{AE2_SENTENCE}\n```" in last.body
    assert dispatcher.status_marks(last.body) == marks("done", "done", "current")


def test_an_open_pull_request_shows_ci_current_then_done_once_its_checks_pass(
        tmp_path: Path) -> None:
    """AE6: in review after the move; ready to merge after its move, and no in-review after it."""
    gh = FakeGitHub({READY: [(ready(74), ())]}, head={"issue-74": (PR,)})
    boss, _ = boss_at(tmp_path, gh, 1, Clock(at(15)), [])
    boss.poll()
    gh.answers = {}
    exits(boss, 74, *(json.dumps(event) for event in AE2_EVENTS))
    boss.poll()
    assert trail(gh)[-2:] == [(74, (IN_REVIEW,)), (74, IN_REVIEW)]
    assert shown(gh, 74)[-1] == (IN_REVIEW, OPENED_MARKS)
    gh.answers = {IN_REVIEW: [(Issue(74, frozenset({IN_REVIEW})), ())]}
    before = len(gh.writes)
    boss.poll()  # its checks are pending: nothing new to say
    assert len(gh.writes) == before
    gh.checks = True
    boss.poll()
    assert trail(gh)[-2:] == [(74, (READY_TO_MERGE,)), (74, READY_TO_MERGE)]
    assert shown(gh, 74)[-1] == (READY_TO_MERGE, (*OPENED_MARKS[:-1], "done"))


def test_a_ready_to_merge_report_that_fails_is_written_at_the_next_poll(tmp_path: Path) -> None:
    """KTD5: no later poll reads a ready-to-merge issue, so the report waits in `pending`."""
    gh = FakeGitHub({IN_REVIEW: [(Issue(74, frozenset({IN_REVIEW})), (PR,))]}, passing=True,
                    comments={74: body_of(IN_REVIEW, OPENED_MARKS)})
    lines: list[str] = []
    boss, _ = boss_at(tmp_path, gh, 1, Clock(at(15)), lines)
    gh.flaky = {"status #74"}
    boss.poll()
    assert trail(gh) == [(74, (READY_TO_MERGE,))]
    assert "dispatcher: #74 status: gh status #74: HTTP 502" in lines
    gh.answers = {}
    boss.poll()
    assert trail(gh) == [(74, (READY_TO_MERGE,)), (74, READY_TO_MERGE)]
    boss.poll()
    assert len(trail(gh)) == 2


def test_an_issue_in_review_before_the_feature_never_gets_a_status_comment(
        tmp_path: Path) -> None:
    """AE8, R12: #60 has no status comment; neither in review nor ready to merge creates one."""
    gh = FakeGitHub({IN_REVIEW: [(Issue(60, frozenset({IN_REVIEW})), (PR,))]})
    boss, _ = boss_at(tmp_path, gh, 1, Clock(at(15)), [])
    boss.poll()
    boss.poll()
    gh.checks = True
    boss.poll()
    assert trail(gh) == [(60, (READY_TO_MERGE,))]
    assert boss.pending == []


def test_a_paused_issue_also_marked_ready_keeps_its_paused_comment(tmp_path: Path) -> None:
    """R11, R3: held, #70 is neither queued nor resumed; #74 waits for the limit's reset."""
    both = paused(70, also=(READY,))
    gh = FakeGitHub({PAUSED: [(both, ())], READY: [(both, ()), (ready(74), ())]},
                    markers={70: limit(70)},
                    comments={70: body_of(PAUSED, marks("done", "done", "paused"),
                                          reset=at(20, 30))})
    clock = Clock(at(18))
    boss, spawn = boss_at(tmp_path, gh, 2, clock, [])
    boss.start()
    clock.now = at(18, 5)
    boss.poll()
    assert spawn.calls == []
    assert trail(gh) == [(74, dispatcher.QUEUED)]
    assert ("Waiting for the Claude usage limit to reset at "
            f"{dispatcher.local_time(at(20, 31))}.") in wrote(gh)[-1].body


def test_a_limit_ending_pauses_the_checklist_and_the_resume_continues_it(tmp_path: Path) -> None:
    """AE7: implementation paused with the reset after the pause move; resumed, then reviewed."""
    gh = FakeGitHub({READY: [(ready(70), ())]})
    clock = Clock(at(15))
    boss, _ = boss_at(tmp_path, gh, 1, clock, [])
    boss.poll()
    gh.answers = {}
    exits(boss, 70, INIT, *(json.dumps(event) for event in AE2_EVENTS), *AT_LIMIT[1:])
    clock.now = at(15, 10)
    boss.poll()
    assert trail(gh)[-2:] == [(70, (PAUSED,)), (70, PAUSED)]
    assert shown(gh, 70)[-1] == (PAUSED, marks("done", "done", "paused"))
    assert f"It resets at {dispatcher.local_time(at(20, 30))}." in wrote(gh)[-1].body
    worktrees(tmp_path, "issue-70")
    gh.answers = {PAUSED: [(paused(70), ())]}
    gh.records[70] = limit(70)
    clock.now = at(20, 35)
    boss.poll()
    assert trail(gh)[-2:] == [(70, (IN_PROGRESS,)), (70, dispatcher.RUNNING)]
    assert shown(gh, 70)[-1] == (dispatcher.RUNNING, marks("done", "done", "current"))
    gh.answers = {}
    logs(boss, 70, skill("ce-code-review"))
    boss.poll()
    assert shown(gh, 70)[-1] == (dispatcher.RUNNING, marks("done", "done", "done", "current"))


def test_a_final_report_that_fails_blocks_nothing_and_is_retried_at_the_next_poll(
        tmp_path: Path) -> None:
    """KTD5: #74's move goes, so do #75's move and report; #74's report waits in `pending`."""
    gh = FakeGitHub({READY: [(ready(74), ()), (ready(75), ())]})
    lines: list[str] = []
    boss, _ = boss_at(tmp_path, gh, 2, Clock(at(15)), lines)
    boss.poll()
    gh.answers = {}
    exits(boss, 74, INIT, result("Stopped: blocked.", error=False))
    exits(boss, 75, INIT, result("Stopped: blocked.", error=False))
    gh.flaky = {"status #74"}
    boss.poll()
    assert trail(gh)[4:] == [(74, (NEEDS_ATTENTION,)), (75, (NEEDS_ATTENTION,)),
                             (75, NEEDS_ATTENTION)]
    assert "dispatcher: #74 status: gh status #74: HTTP 502" in lines
    boss.poll()
    assert trail(gh)[7:] == [(74, NEEDS_ATTENTION)]
    assert shown(gh, 74)[-1] == (NEEDS_ATTENTION, marks("failed"))
    boss.poll()
    assert len(trail(gh)) == 8


def test_a_failing_running_report_is_only_logged(tmp_path: Path) -> None:
    """KTD5: the next poll recomputes it; #75's report and #76's queued one still go."""
    gh = FakeGitHub({READY: [(ready(74), ()), (ready(75), ())]})
    lines: list[str] = []
    boss, _ = boss_at(tmp_path, gh, 2, Clock(at(15)), lines)
    boss.poll()
    gh.answers = {READY: [(ready(76), ())]}
    logs(boss, 74, skill("ce-work"))
    logs(boss, 75, skill("ce-work"))
    gh.flaky = {"status #74"}
    boss.poll()
    assert "dispatcher: #74 status: gh status #74: HTTP 502" in lines
    assert boss.pending == []
    assert trail(gh)[4:] == [(75, dispatcher.RUNNING), (76, dispatcher.QUEUED)]
    boss.poll()
    assert trail(gh)[6:] == [(74, dispatcher.RUNNING)]
    assert shown(gh, 74)[-1] == (dispatcher.RUNNING, marks("skipped", "skipped", "current"))


def test_an_orphan_at_start_fails_the_stage_its_comment_held(tmp_path: Path) -> None:
    """R9: #75's comment said implementation; listing #74's fails, is said, and start goes on.

    No later poll reads an issue that needs attention, so #74's report waits in `pending` and
    lands at the first poll.
    """
    gh = FakeGitHub({IN_PROGRESS: [(Issue(74, frozenset({IN_PROGRESS})), ()),
                                   (Issue(75, frozenset({IN_PROGRESS})), ())],
                     PAUSED: [(paused(70), ())]},
                    markers={70: limit(70)},
                    comments={74: body_of(dispatcher.RUNNING, marks("current")),
                              75: body_of(dispatcher.RUNNING, marks("done", "done", "current"))})
    gh.flaky = {"list #74"}
    lines: list[str] = []
    boss, _ = boss_at(tmp_path, gh, 2, Clock(at(18)), lines)
    boss.sessions.git = lambda args: ""
    boss.start()
    assert trail(gh) == [(74, (NEEDS_ATTENTION,)), (75, (NEEDS_ATTENTION,)), (75, NEEDS_ATTENTION)]
    assert shown(gh, 75) == [(NEEDS_ATTENTION, marks("done", "done", "failed"))]
    assert "dispatcher: #74 status: gh list #74: HTTP 502" in lines
    assert any("no session starts until" in line for line in lines)
    boss.poll()
    assert shown(gh, 74) == [(NEEDS_ATTENTION, marks("failed"))]
    assert boss.pending == []


def test_a_session_that_cannot_start_shows_the_plan_failed(tmp_path: Path) -> None:
    """R9: after the needs-attention move; a failed report waits in `pending`."""
    gh = FakeGitHub({READY: [(ready(74), ())]})
    runner, _ = sessions(tmp_path, FakeGit(fail="worktree add"))
    boss = dispatcher.Dispatcher(gh, runner, 1, say=lambda line: None)
    gh.flaky = {"status #74"}
    boss.poll()
    assert trail(gh) == [(74, (IN_PROGRESS,)), (74, (NEEDS_ATTENTION,))]
    gh.answers = {}
    boss.poll()
    assert trail(gh)[2:] == [(74, NEEDS_ATTENTION)]
    assert shown(gh, 74) == [(NEEDS_ATTENTION, marks("failed"))]


def test_a_resume_that_cannot_start_fails_its_paused_stage(tmp_path: Path) -> None:
    """R9: the worktree is gone; the comment's paused implementation fails."""
    gh = FakeGitHub({PAUSED: [(paused(70), ())]}, markers={70: limit(70)},
                    comments={70: body_of(PAUSED, marks("done", "done", "paused"),
                                          reset=at(20, 30))})
    boss, _ = boss_at(tmp_path, gh, 1, Clock(at(21)), [])
    boss.poll()
    assert trail(gh) == [(70, (IN_PROGRESS,)), (70, (NEEDS_ATTENTION,)), (70, NEEDS_ATTENTION)]
    assert shown(gh, 70) == [(NEEDS_ATTENTION, marks("done", "done", "failed"))]


def test_a_resume_whose_comment_cannot_be_read_waits_for_the_next_poll(tmp_path: Path) -> None:
    """KTD2: its marks live only there; resumed without them, the checklist would start over."""
    worktrees(tmp_path, "issue-70")
    gh = FakeGitHub({PAUSED: [(paused(70), ())]}, markers={70: limit(70)},
                    comments={70: body_of(PAUSED, marks("done", "done", "paused"))})
    boss, spawn = boss_at(tmp_path, gh, 1, Clock(at(21)), [])
    gh.flaky = {"list #70"}
    boss.poll()
    assert spawn.calls == []
    assert trail(gh) == []
    boss.poll()
    assert trail(gh) == [(70, (IN_PROGRESS,)), (70, dispatcher.RUNNING)]
    assert shown(gh, 70) == [(dispatcher.RUNNING, marks("done", "done", "current"))]


def test_only_a_session_this_run_dispatched_gets_its_status_comment_created(
        tmp_path: Path) -> None:
    """R12: #70, resumed with no comment, never gets one; #74's failed create comes next poll."""
    worktrees(tmp_path, "issue-70")
    gh = FakeGitHub({PAUSED: [(paused(70), ())], READY: [(ready(74), ())]},
                    markers={70: limit(70)})
    boss, _ = boss_at(tmp_path, gh, 2, Clock(at(21)), [])
    gh.flaky = {"status #74"}
    boss.poll()
    assert trail(gh) == [(70, (IN_PROGRESS,)), (74, (IN_PROGRESS,))]
    gh.answers = {}
    logs(boss, 70, skill("ce-work"))
    boss.poll()
    assert trail(gh)[2:] == [(74, dispatcher.RUNNING)]
    assert wrote(gh)[-1].posted


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
def test_a_signal_ends_the_loop_then_leaves() -> None:
    """Ctrl-C during a poll ends the loop, then `stop` leaves: it judges what ended."""
    boss = Boss(lambda: signal.raise_signal(signal.SIGINT))
    dispatcher.serve(boss, 0)  # type: ignore[arg-type]
    assert boss.calls == ["start", "dispatcher: a poll every 0s; Ctrl-C stops", "poll",
                          "dispatcher: stopping", "stop"]


@pytest.mark.usefixtures("handlers")
def test_an_unexpected_error_still_leaves_through_stop() -> None:
    """A bug ends the dispatcher through `stop` too, once, before it propagates."""
    def broken() -> None:
        raise RuntimeError("a bug")

    boss = Boss(broken)
    with pytest.raises(RuntimeError, match="a bug"):
        dispatcher.serve(boss, 0)  # type: ignore[arg-type]
    assert boss.calls[-1] == "stop"
    assert boss.calls.count("stop") == 1


@pytest.mark.usefixtures("handlers")
def test_an_error_from_a_poll_leaves_the_live_sessions_running(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R1: the dispatcher dies of a bug while #74 runs: #74 runs on, in progress, recorded."""
    gh = FakeGitHub({READY: [(ready(74), ())]})
    lines: list[str] = []
    boss, _ = boss_at(tmp_path, gh, 1, Clock(at(15)), lines)
    boss.poll()
    gh.answers = {}
    process = boss.running[74].process
    assert isinstance(process, FakeProcess)
    written = len(gh.writes)

    def broken() -> None:
        raise RuntimeError("a bug")

    monkeypatch.setattr(boss, "poll", broken)
    with pytest.raises(RuntimeError, match="a bug"):
        dispatcher.serve(boss, 0)
    assert process.signals == []
    assert [write for write in gh.writes[written:] if isinstance(write, Move | Wrote)] == []
    assert lines[-1] == (f"dispatcher: #74 left running (PID {process.pid}), "
                         "the next start follows it")
    assert record_file(tmp_path, 74).exists()


def command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
            serve: Callable[[object, float], None]) -> Path:
    """main() over trivial gateways and this serve(): the lock it would take."""
    monkeypatch.setattr(dispatcher, "ROOT", tmp_path)
    monkeypatch.setattr(dispatcher, "GitHub", lambda: object())
    monkeypatch.setattr(dispatcher, "Sessions", lambda root: object())
    monkeypatch.setattr(dispatcher, "serve", serve)
    return tmp_path / dispatcher.STATE / "lock"


def test_the_lock_is_held_while_serving_and_its_file_stays_after(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locks: list[int]) -> None:
    """KTD6: a process waiting on the lock file while the dispatcher runs gets the lock on
    the same file once it exits: the file is never removed."""
    waiting: list[int] = []

    def serve(boss: object, every: float) -> None:
        assert lock.read_text() == str(os.getpid())
        waiting.append(os.open(lock, os.O_RDWR))
        locks.append(waiting[0])
        with pytest.raises(BlockingIOError):
            fcntl.flock(waiting[0], fcntl.LOCK_EX | fcntl.LOCK_NB)

    lock = command(tmp_path, monkeypatch, serve)
    assert dispatcher.main(["dispatcher.py", "run", "--every", "0"]) == 0
    assert lock.exists()
    fcntl.flock(waiting[0], fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert os.fstat(waiting[0]).st_ino == lock.stat().st_ino


def test_the_lock_is_released_when_serving_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                 locks: list[int]) -> None:
    def serve(boss: object, every: float) -> None:
        raise RuntimeError("a bug")

    lock = command(tmp_path, monkeypatch, serve)
    with pytest.raises(RuntimeError, match="a bug"):
        dispatcher.main(["dispatcher.py", "run", "--every", "0"])
    assert lock.exists()
    hold(lock, locks)


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
    assert "#74 was in progress with no session record: it needs attention" in text


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


# A restart: what the last run left

def in_progress(*numbers: int) -> list[tuple[Issue, tuple[PullRequest, ...]]]:
    return [(Issue(number, frozenset({IN_PROGRESS})), ()) for number in numbers]


def earlier(tmp_path: Path, gh: FakeGitHub, *numbers: int) -> dict[int, int]:
    """An earlier dispatcher dispatched these ready issues and was stopped: each session left
    running with its record. GitHub then answers them in progress; their PIDs, by issue."""
    gh.answers = {READY: [(ready(number), ()) for number in numbers]}
    runner, _ = sessions(tmp_path, FakeGit())
    boss = dispatcher.Dispatcher(gh, runner, len(numbers), say=lambda line: None)
    boss.poll()
    pids = {number: boss.running[number].process.pid for number in numbers}
    boss.stop()
    gh.answers = {IN_PROGRESS: in_progress(*numbers)}
    return pids


def writes_log(tmp_path: Path, issue: int, *events: str) -> None:
    """The issue's session, left running, writes these events to its log."""
    path = tmp_path / dispatcher.STATE / f"logs/issue-{issue}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as log:
        log.write("".join(line + "\n" for line in events))


def restamp(tmp_path: Path, issue: int, started: float) -> None:
    """The issue's record says its session started at `started`."""
    record = json.loads(record_file(tmp_path, issue).read_text())
    record["started"] = started
    record_file(tmp_path, issue).write_text(json.dumps(record))


def restarted(tmp_path: Path, gh: FakeGitHub, slots: int, clock: Clock, lines: list[str],
              *gone: int) -> tuple[dispatcher.Dispatcher, FakeSpawn, FakePs, FakeKillpg]:
    """A new dispatcher on the same state folder; the `gone` PIDs' processes no longer exist."""
    boss, spawn = boss_at(tmp_path, gh, slots, clock, lines)
    ps, killpg = fakes(boss.sessions)
    for pid in gone:
        ps.starts[pid] = None
    return boss, spawn, ps, killpg


def started_lines(lines: list[str]) -> list[str]:
    """What start said of each issue it found, the labels' and the paused issues' lines aside."""
    return [line for line in lines
            if line.startswith("dispatcher: #") and " -> " not in line]


def test_a_session_left_running_is_followed_again_after_a_restart(tmp_path: Path) -> None:
    """AE1, R3: same PID, no move, no comment at start; minutes from the record's start."""
    gh = FakeGitHub()
    pids = earlier(tmp_path, gh, 70)
    restamp(tmp_path, 70, at(14, 30))
    writes_log(tmp_path, 70, INIT, *(json.dumps(event) for event in AE2_EVENTS))
    written = list(gh.writes)
    lines: list[str] = []
    clock = Clock(at(15))
    boss, spawn, _, killpg = restarted(tmp_path, gh, 2, clock, lines)
    boss.start()
    assert gh.writes == [*written, "labels"]
    assert started_lines(lines) == [
        f"dispatcher: #70 still running (PID {pids[70]}): followed again"]
    assert boss.running[70].process.pid == pids[70]
    boss.poll()
    assert any(line.startswith("dispatcher: #70 still running (30 min), log ") for line in lines)
    assert [(write.posted, state_of(write.body)) for write in wrote(gh)] == [
        (True, dispatcher.RUNNING), (False, dispatcher.RUNNING)]
    assert wrote(gh)[-1].body.startswith("**Dispatcher status: implementation** (running 30 min)")
    assert spawn.calls == []
    assert killpg.calls == []
    assert record_file(tmp_path, 70).exists()


def test_a_followed_session_continues_its_resumes_checklist(tmp_path: Path) -> None:
    """KTD9: a resumed session left running reports from its record's start marks."""
    worktrees(tmp_path, "issue-70")
    gh = FakeGitHub({PAUSED: [(paused(70), ())]}, markers={70: limit(70)},
                    comments={70: body_of(PAUSED, marks("done", "done", "paused"))})
    boss, _ = boss_at(tmp_path, gh, 1, Clock(at(20, 35)), [])
    boss.poll()
    pid = boss.running[70].process.pid
    boss.stop()
    gh.answers = {IN_PROGRESS: in_progress(70)}
    restamp(tmp_path, 70, at(20, 35))
    again, _, _, _ = restarted(tmp_path, gh, 1, Clock(at(21, 5)), [])
    again.start()
    assert again.running[70].process.pid == pid
    writes_log(tmp_path, 70, json.dumps(skill("ce-code-review")))
    again.poll()
    assert [write.posted for write in wrote(gh)] == [False, False]
    assert shown(gh, 70)[-1] == (dispatcher.RUNNING, marks("done", "done", "done", "current"))
    assert "(running 30 min)" in wrote(gh)[-1].body


def test_a_session_that_opened_its_pull_request_while_no_dispatcher_ran_is_in_review(
        tmp_path: Path) -> None:
    """AE2, R5: judged at start from its log; the record goes once the verdict is in."""
    gh = FakeGitHub(head={"issue-70": (PR,)})
    pids = earlier(tmp_path, gh, 70)
    writes_log(tmp_path, 70, INIT, *(json.dumps(event) for event in AE2_EVENTS),
               json.dumps(skill("ce-commit-push-pr")),
               result("Opened #101.", error=False))
    lines: list[str] = []
    boss, _, _, killpg = restarted(tmp_path, gh, 2, Clock(at(15)), lines, pids[70])
    boss.start()
    assert moves(gh)[1:] == [(70, (IN_REVIEW,))]
    assert Link(101, 70) in gh.writes
    assert shown(gh, 70)[-1] == (IN_REVIEW, OPENED_MARKS)
    assert not record_file(tmp_path, 70).exists()
    assert boss.running == {}
    assert killpg.calls == []
    assert started_lines(lines) == [
        "dispatcher: #70 session ended while no dispatcher ran: in review"]


def test_a_session_that_ended_with_an_error_while_no_dispatcher_ran_needs_attention(
        tmp_path: Path) -> None:
    """R5, KTD3: a final result and no pull request, as a poll would have judged it."""
    gh = FakeGitHub()
    pids = earlier(tmp_path, gh, 70)
    writes_log(tmp_path, 70, INIT, result("API Error: overloaded"))
    boss, _, _, _ = restarted(tmp_path, gh, 2, Clock(at(15)), [], pids[70])
    boss.start()
    assert moves(gh)[1:] == [(70, (NEEDS_ATTENTION,))]
    assert "Reason: API Error: overloaded" in (last_move(gh).comment or "")
    assert shown(gh, 70)[-1] == (NEEDS_ATTENTION, marks("failed"))
    assert not record_file(tmp_path, 70).exists()


def test_an_interrupted_session_is_paused_then_resumes_in_its_own_worktree(
        tmp_path: Path) -> None:
    """AE3, R7, R8, KTD9: paused as interrupted at start, resumed at the first poll, no new
    worktree, its checklist continued."""
    gh = FakeGitHub()
    pids = earlier(tmp_path, gh, 70)
    worktrees(tmp_path, "issue-70")
    writes_log(tmp_path, 70, INIT, *(json.dumps(event) for event in AE2_EVENTS))
    lines: list[str] = []
    boss, spawn, _, _ = restarted(tmp_path, gh, 2, Clock(at(15)), lines, pids[70])
    boss.start()
    pause = last_move(gh)
    assert (pause.add, pause.comment_first) == ((PAUSED,), True)
    marker = dispatcher.marker_of(pause.comment or "", 70)
    assert marker == cause(70, INTERRUPTED)
    assert "Worktree: `.claude/worktrees/issue-70`" in (pause.comment or "")
    assert shown(gh, 70)[-1] == (PAUSED, marks("done", "done", "paused"))
    assert "The session was interrupted" in wrote(gh)[-1].body
    assert started_lines(lines) == [
        "dispatcher: #70 session ended while no dispatcher ran: paused as interrupted"]
    assert not record_file(tmp_path, 70).exists()
    gh.answers = {PAUSED: [(paused(70), ())]}
    gh.records[70] = marker
    boss.poll()
    (args, options), = resumes(spawn)
    assert args[3] == SESSION
    assert "was interrupted" in args[4]
    assert options["cwd"] == tmp_path / ".claude/worktrees/issue-70"
    git = boss.sessions.git
    assert isinstance(git, FakeGit)
    assert not [call for call in git.calls if call[:2] == ["worktree", "add"]]
    assert moves(gh)[-1] == (70, (IN_PROGRESS,))
    assert shown(gh, 70)[-1] == (dispatcher.RUNNING, marks("done", "done", "current"))
    assert not [line for line in lines if "usage limit" in line]


def test_a_fresh_session_killed_before_its_first_event_needs_attention(tmp_path: Path) -> None:
    """R9, KTD5: no conversation in its slice, so nothing to resume."""
    gh = FakeGitHub()
    pids = earlier(tmp_path, gh, 70)
    lines: list[str] = []
    boss, _, _, _ = restarted(tmp_path, gh, 2, Clock(at(15)), lines, pids[70])
    boss.start()
    assert moves(gh)[1:] == [(70, (NEEDS_ATTENTION,))]
    comment = last_move(gh).comment or ""
    assert "no final result; its exit code is unknown" in comment
    assert "Log: `tools/dispatcher/.state/logs/issue-70.log`" in comment
    assert started_lines(lines) == [
        "dispatcher: #70 session ended while no dispatcher ran: needs attention"]
    assert not record_file(tmp_path, 70).exists()


def test_a_resumed_session_interrupted_before_its_first_event_resumes_its_marker(
        tmp_path: Path) -> None:
    """KTD5: the marker it came from, never an earlier attempt's conversation in the log."""
    worktrees(tmp_path, "issue-70")
    writes_log(tmp_path, 70, event("system", OTHER, subtype="init"))  # an earlier attempt
    gh = FakeGitHub({PAUSED: [(paused(70), ())]}, markers={70: limit(70)})
    first, _ = boss_at(tmp_path, gh, 1, Clock(at(20, 35)), [])
    first.poll()
    pid = first.running[70].process.pid
    first.stop()
    gh.answers = {IN_PROGRESS: in_progress(70)}
    boss, spawn, _, _ = restarted(tmp_path, gh, 1, Clock(at(21)), [], pid)
    boss.start()
    marker = dispatcher.marker_of(last_move(gh).comment or "", 70)
    assert marker == cause(70, INTERRUPTED)
    gh.answers = {PAUSED: [(paused(70), ())]}
    gh.records[70] = marker
    boss.poll()
    assert [args[3] for args, _ in resumes(spawn)] == [SESSION]


def test_an_interrupted_issue_whose_worktree_is_gone_needs_attention_at_its_resume(
        tmp_path: Path) -> None:
    """AE4, R9: the missing worktree and the log, named inside the checkout."""
    gh = FakeGitHub()
    pids = earlier(tmp_path, gh, 70)
    writes_log(tmp_path, 70, INIT)
    boss, spawn, _, _ = restarted(tmp_path, gh, 2, Clock(at(15)), [], pids[70])
    boss.start()
    gh.answers = {PAUSED: [(paused(70), ())]}
    gh.records[70] = cause(70, INTERRUPTED)
    boss.poll()
    assert moves(gh)[1:] == [(70, (PAUSED,)), (70, (IN_PROGRESS,)), (70, (NEEDS_ATTENTION,))]
    comment = last_move(gh).comment or ""
    assert "Worktree: `.claude/worktrees/issue-70`" in comment
    assert "Log: `tools/dispatcher/.state/logs/issue-70.log`" in comment
    assert str(tmp_path) not in comment
    assert spawn.calls == []


def test_sessions_followed_again_take_the_slots_first(tmp_path: Path) -> None:
    """AE5, R4: with one slot, #74 waits until both left-running sessions have ended."""
    gh = FakeGitHub(head={"issue-70": (PR,), "issue-72": (PR,)})
    pids = earlier(tmp_path, gh, 70, 72)
    gh.answers[READY] = [(ready(74), ())]
    lines: list[str] = []
    boss, spawn, ps, killpg = restarted(tmp_path, gh, 1, Clock(at(15)), lines)
    boss.start()
    boss.poll()
    assert spawn.calls == []
    assert "dispatcher: #74: waiting for a free session (2 of 1 in use)" in lines
    gh.answers = {READY: [(ready(74), ())]}
    ps.starts[pids[70]] = None
    boss.poll()
    assert spawn.calls == []
    assert set(boss.running) == {72}
    ps.starts[pids[72]] = None
    boss.poll()
    assert len(spawn.calls) == 1
    assert set(boss.running) == {74}
    assert killpg.calls == []


def test_a_process_reusing_the_pid_is_not_the_session(tmp_path: Path) -> None:
    """R6: another start time: the session is gone, judged, and nothing is signalled."""
    gh = FakeGitHub()
    pids = earlier(tmp_path, gh, 70)
    writes_log(tmp_path, 70, INIT)
    worktrees(tmp_path, "issue-70")
    boss, _, ps, killpg = restarted(tmp_path, gh, 2, Clock(at(15)), [])
    ps.starts[pids[70]] = "Thu Oct  1 19:42:07 2026"
    boss.start()
    assert boss.running == {}
    assert moves(gh)[1:] == [(70, (PAUSED,))]
    boss.stop()
    assert killpg.calls == []


def test_a_session_whose_issue_left_progress_is_left_alone(tmp_path: Path) -> None:
    """KTD7: not followed, never signalled; its record goes only once its process is gone."""
    gh = FakeGitHub()
    pids = earlier(tmp_path, gh, 74)
    gh.answers = {}  # the author took #74 out of the dispatcher's hands
    written = list(gh.writes)
    lines: list[str] = []
    boss, _, _, killpg = restarted(tmp_path, gh, 2, Clock(at(15)), lines)
    boss.start()
    boss.poll()
    boss.stop()
    assert boss.running == {}
    assert killpg.calls == []
    assert gh.writes == [*written, "labels"]
    assert record_file(tmp_path, 74).exists()
    assert started_lines(lines) == [
        f"dispatcher: #74 is not in progress: its session (PID {pids[74]}) is left alone"]
    lines.clear()
    again, _, _, _ = restarted(tmp_path, gh, 2, Clock(at(16)), lines, pids[74])
    again.start()
    assert not record_file(tmp_path, 74).exists()
    assert gh.writes == [*written, "labels", "labels"]
    assert started_lines(lines) == [
        "dispatcher: #74 is not in progress: its session is gone, its record removed"]


def test_an_unreadable_record_is_said_and_its_issue_needs_attention(tmp_path: Path) -> None:
    """Risks: outside damage never crashes the start; the issue is one with no record."""
    gh = FakeGitHub({IN_PROGRESS: in_progress(74)})
    record_file(tmp_path, 74).parent.mkdir(parents=True)
    record_file(tmp_path, 74).write_text("{")
    record_file(tmp_path, 75).write_text("{")
    lines: list[str] = []
    boss, _, _, _ = restarted(tmp_path, gh, 2, Clock(at(15)), lines)
    boss.sessions.git = lambda args: ""
    boss.start()
    assert moves(gh) == [(74, (NEEDS_ATTENTION,))]
    assert "no session running" in (last_move(gh).comment or "")
    assert started_lines(lines) == [
        "dispatcher: #74 was in progress with an unreadable session record: it needs attention",
        f"dispatcher: #75: its session record {record_file(tmp_path, 75)} cannot be read"]


def test_start_says_what_happened_to_each_issue_in_progress(tmp_path: Path) -> None:
    """R13: followed again, judged, paused as interrupted, needing attention; one line each."""
    gh = FakeGitHub(head={"issue-72": (PR,)})
    pids = earlier(tmp_path, gh, 70, 72, 73, 74)
    writes_log(tmp_path, 73, INIT)
    writes_log(tmp_path, 74, INIT, result("Stopped: the plan returned blocked."))
    gh.answers = {IN_PROGRESS: in_progress(70, 72, 73, 74, 75)}
    lines: list[str] = []
    boss, _, _, _ = restarted(tmp_path, gh, 4, Clock(at(15)), lines,
                              pids[72], pids[73], pids[74])
    boss.sessions.git = lambda args: ""
    boss.start()
    assert started_lines(lines) == [
        f"dispatcher: #70 still running (PID {pids[70]}): followed again",
        "dispatcher: #72 session ended while no dispatcher ran: in review",
        "dispatcher: #73 session ended while no dispatcher ran: paused as interrupted",
        "dispatcher: #74 session ended while no dispatcher ran: needs attention",
        "dispatcher: #75 was in progress with no session record: it needs attention"]
    assert not [line for line in lines if "no issue left in progress" in line]


def test_a_followed_session_that_exits_at_a_poll_is_judged_like_any_other(
        tmp_path: Path) -> None:
    """KTD2, KTD3: at a poll, no final result needs attention; the exit code is unknown."""
    gh = FakeGitHub()
    pids = earlier(tmp_path, gh, 70)
    lines: list[str] = []
    boss, _, ps, _ = restarted(tmp_path, gh, 2, Clock(at(15)), lines)
    boss.start()
    writes_log(tmp_path, 70, INIT)
    ps.starts[pids[70]] = None
    gh.answers = {}
    boss.poll()
    log = tmp_path / dispatcher.STATE / "logs/issue-70.log"
    assert f"dispatcher: #70 session ended (exit code unknown), log {log}" in lines
    assert moves(gh)[1:] == [(70, (NEEDS_ATTENTION,))]
    assert "its exit code is unknown" in (last_move(gh).comment or "")
    assert not record_file(tmp_path, 70).exists()


def test_a_session_this_run_started_with_no_final_result_needs_attention(tmp_path: Path) -> None:
    """KTD3: at a poll it never pauses as interrupted, its conversation known or not."""
    gh = FakeGitHub({READY: [(ready(70), ())]})
    boss, _ = boss_at(tmp_path, gh, 1, Clock(at(15)), [])
    boss.poll()
    gh.answers = {}
    exits(boss, 70, INIT)
    boss.poll()
    assert moves(gh) == [(70, (IN_PROGRESS,)), (70, (NEEDS_ATTENTION,))]
    assert "exited with code 0 and no final result" in (last_move(gh).comment or "")


def test_the_dispatcher_is_updated_while_a_session_runs(tmp_path: Path) -> None:
    """F1: start, dispatch, leave; a new dispatcher follows the session, which then opens its
    pull request and exits: in review, as if no one had left."""
    gh = FakeGitHub({READY: [(ready(70), ())]}, head={"issue-70": (PR,)})
    lines: list[str] = []
    first, _ = boss_at(tmp_path, gh, 1, Clock(at(15)), lines)
    first.start()
    first.poll()
    process = first.running[70].process
    assert isinstance(process, FakeProcess)
    first.stop()
    assert process.signals == []
    gh.answers = {IN_PROGRESS: in_progress(70)}
    boss, spawn, ps, killpg = restarted(tmp_path, gh, 1, Clock(at(15, 5)), lines)
    boss.start()
    assert boss.running[70].process.pid == process.pid
    gh.answers = {}
    boss.poll()
    assert spawn.calls == []
    writes_log(tmp_path, 70, INIT, *(json.dumps(event) for event in AE2_EVENTS),
               json.dumps(skill("ce-commit-push-pr")),
               result("Opened #101.", error=False))
    ps.starts[process.pid] = None
    boss.poll()
    assert moves(gh) == [(70, (IN_PROGRESS,)), (70, (IN_REVIEW,))]
    assert Link(101, 70) in gh.writes
    assert [write.posted for write in wrote(gh)].count(True) == 1
    assert shown(gh, 70)[-1] == (IN_REVIEW, OPENED_MARKS)
    assert not record_file(tmp_path, 70).exists()
    assert killpg.calls == []
    assert boss.running == {}


# The stop command

class Waits:
    """`stop`'s wait for the lock: a clock its sleeps move; `then` runs at the `at`th sleep."""

    def __init__(self, at: int | None = None, then: Callable[[], None] = lambda: None) -> None:
        self.now = 0.0
        self.slept = 0
        self.at = at
        self.then = then

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept += 1
        self.now += seconds
        if self.slept == self.at:
            self.then()


def halts(tmp_path: Path, boss: dispatcher.Dispatcher, *,
          kill: Callable[[int, int], None] | None = None, waits: Waits | None = None) -> int:
    """`dispatcher.py stop` over this state folder; no real process is ever signalled."""
    def refuse(pid: int, signum: int) -> None:
        pytest.fail(f"no dispatcher to signal, yet PID {pid} was")

    waits = waits or Waits()
    return dispatcher.halt(tmp_path / dispatcher.STATE / "lock", boss, kill=kill or refuse,
                           clock=waits.clock, sleep=waits.sleep)


def pause_moves(gh: FakeGitHub) -> dict[int, Move]:
    """Each issue's last move to paused."""
    return {write.issue: write for write in gh.writes
            if isinstance(write, Move) and write.add == (PAUSED,)}


def test_stop_ends_every_session_pauses_each_issue_and_the_next_run_resumes_them(
        tmp_path: Path) -> None:
    """AE6, R10, R12, KTD9: both process groups end, both issues go paused as stopped, their
    status comments say so, and the next start resumes both with the stopped prompt."""
    gh = FakeGitHub()
    pids = earlier(tmp_path, gh, 70, 73)
    worktrees(tmp_path, "issue-70", "issue-73")
    writes_log(tmp_path, 70, INIT, *(json.dumps(event) for event in AE2_EVENTS))
    writes_log(tmp_path, 73, INIT)
    lines: list[str] = []
    boss, _, _, killpg = restarted(tmp_path, gh, 0, Clock(at(15)), lines)
    assert halts(tmp_path, boss) == 0
    assert killpg.calls == [(pids[70], signal.SIGTERM), (pids[73], signal.SIGTERM)]
    assert moves(gh)[2:] == [(70, (PAUSED,)), (73, (PAUSED,))]
    paused_by = pause_moves(gh)
    for issue in (70, 73):
        assert dispatcher.marker_of(paused_by[issue].comment or "", issue) == cause(issue, STOPPED)
        assert shown(gh, issue)[-1][0] == PAUSED
        body = [write.body for write in wrote(gh) if write.issue == issue][-1]
        assert "stopped with `dispatcher.py stop`" in body
        assert not record_file(tmp_path, issue).exists()
    assert shown(gh, 70)[-1] == (PAUSED, marks("done", "done", "paused"))
    assert lines == [
        "dispatcher: no dispatcher runs",
        f"dispatcher: ending the sessions of #70 (PID {pids[70]}), #73 (PID {pids[73]})...",
        "dispatcher: #70 session stopped: paused as stopped",
        "dispatcher: #70 -> paused",
        "dispatcher: #73 session stopped: paused as stopped",
        "dispatcher: #73 -> paused"]
    gh.answers = {PAUSED: [(paused(70), ()), (paused(73), ())]}
    gh.records = {issue: cause(issue, STOPPED) for issue in (70, 73)}
    again, spawn, _, _ = restarted(tmp_path, gh, 2, Clock(at(15, 5)), [])
    again.start()
    again.poll()
    assert [(args[3], options["cwd"].name) for args, options in resumes(spawn)] == [
        (SESSION, "issue-70"), (SESSION, "issue-73")]
    assert all("was stopped with `dispatcher.py stop`" in args[4]
               for args, _ in resumes(spawn))
    assert NEEDS_ATTENTION not in [label for _, added in moves(gh) for label in added]


def test_stop_stops_a_running_dispatcher_before_the_sessions(tmp_path: Path,
                                                             locks: list[int]) -> None:
    """R11, KTD6: SIGTERM to the PID in the held lock, a wait for the lock, then the sessions."""
    gh = FakeGitHub()
    pids = earlier(tmp_path, gh, 70)
    writes_log(tmp_path, 70, INIT)
    lock = tmp_path / dispatcher.STATE / "lock"
    running = hold(lock, locks, 4242)
    order: list[object] = []

    def exits() -> None:
        locks.remove(running)
        os.close(running)
        order.append("exited")

    lines: list[str] = []
    boss, _, _, killpg = restarted(tmp_path, gh, 0, Clock(at(15)), lines)
    end = boss.sessions.end

    def ending(sessions: Any) -> None:
        order.append("end")
        end(sessions)

    boss.sessions.end = ending  # type: ignore[method-assign]
    assert halts(tmp_path, boss, kill=lambda pid, signum: order.append((pid, signum)),
                 waits=Waits(3, exits)) == 0
    assert order == [(4242, signal.SIGTERM), "exited", "end"]
    assert killpg.calls == [(pids[70], signal.SIGTERM)]
    assert lines[:2] == ["dispatcher: stopping the dispatcher (PID 4242)...",
                         "dispatcher: the dispatcher (PID 4242) stopped"]
    assert moves(gh)[1:] == [(70, (PAUSED,))]
    assert lock.read_text() == str(os.getpid())
    hold(lock, locks)  # stop released it


def test_a_dispatcher_that_never_releases_the_lock_makes_stop_change_nothing(
        tmp_path: Path, locks: list[int]) -> None:
    """KTD6: a bounded wait, then a report; no session is ended, no record or label touched."""
    gh = FakeGitHub()
    earlier(tmp_path, gh, 70)
    lock = tmp_path / dispatcher.STATE / "lock"
    hold(lock, locks, 4242)
    record = record_file(tmp_path, 70).read_text()
    written = list(gh.writes)
    lines: list[str] = []
    boss, _, _, killpg = restarted(tmp_path, gh, 0, Clock(at(15)), lines)
    signals: list[tuple[int, int]] = []
    waits = Waits()
    assert halts(tmp_path, boss, kill=lambda pid, signum: signals.append((pid, signum)),
                 waits=waits) == 1
    assert signals == [(4242, signal.SIGTERM)]
    assert waits.now >= dispatcher.WAIT
    assert killpg.calls == []
    assert gh.writes == written
    assert record_file(tmp_path, 70).read_text() == record
    assert lock.read_text() == "4242"
    assert lines[-1] == (f"dispatcher: the dispatcher (PID 4242) did not stop within "
                         f"{dispatcher.WAIT:g}s; nothing was changed")


def test_a_run_started_while_stop_holds_the_lock_refuses(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """KTD6: stop holds the lock for its whole run, so no dispatcher starts in the middle."""
    gh = FakeGitHub()
    earlier(tmp_path, gh, 70)
    boss, _, _, _ = restarted(tmp_path, gh, 0, Clock(at(15)), [])
    monkeypatch.setattr(dispatcher, "ROOT", tmp_path)
    monkeypatch.setattr(dispatcher, "GitHub", lambda: pytest.fail("no gh call when refusing"))
    refused: list[int] = []
    end = boss.sessions.end

    def ending(sessions: Any) -> None:
        refused.append(dispatcher.main(["dispatcher.py", "run"]))
        end(sessions)

    monkeypatch.setattr(boss.sessions, "end", ending)
    assert halts(tmp_path, boss) == 0
    assert refused == [1]
    assert f"(PID {os.getpid()})" in capsys.readouterr().out


def test_stop_after_a_machine_restart_pauses_a_dead_session_as_interrupted(
        tmp_path: Path) -> None:
    """KTD3: gone with no final result and a known conversation, judged as at start."""
    gh = FakeGitHub()
    pids = earlier(tmp_path, gh, 70)
    writes_log(tmp_path, 70, INIT)
    lines: list[str] = []
    boss, _, _, killpg = restarted(tmp_path, gh, 0, Clock(at(15)), lines, pids[70])
    assert halts(tmp_path, boss) == 0
    assert killpg.calls == []
    assert moves(gh)[1:] == [(70, (PAUSED,))]
    assert dispatcher.marker_of(last_move(gh).comment or "", 70) == cause(70, INTERRUPTED)
    assert lines == ["dispatcher: no dispatcher runs",
                     "dispatcher: #70 session ended while no dispatcher ran: paused as interrupted",
                     "dispatcher: #70 -> paused"]
    assert not record_file(tmp_path, 70).exists()


def test_a_stopped_session_that_wrote_a_clean_final_result_still_pauses_as_stopped(
        tmp_path: Path) -> None:
    """KTD3: the stopped flag comes before the final result."""
    gh = FakeGitHub()
    earlier(tmp_path, gh, 70)
    writes_log(tmp_path, 70, INIT, result("Done.", error=False))
    boss, _, _, _ = restarted(tmp_path, gh, 0, Clock(at(15)), [])
    assert halts(tmp_path, boss) == 0
    assert moves(gh)[1:] == [(70, (PAUSED,))]
    assert dispatcher.marker_of(last_move(gh).comment or "", 70) == cause(70, STOPPED)


def test_a_stopped_session_with_an_open_pull_request_goes_in_review(tmp_path: Path) -> None:
    """KTD3: an open pull request comes first."""
    gh = FakeGitHub(head={"issue-70": (PR,)})
    earlier(tmp_path, gh, 70)
    writes_log(tmp_path, 70, INIT)
    lines: list[str] = []
    boss, _, _, _ = restarted(tmp_path, gh, 0, Clock(at(15)), lines)
    assert halts(tmp_path, boss) == 0
    assert moves(gh)[1:] == [(70, (IN_REVIEW,))]
    assert Link(101, 70) in gh.writes
    assert "dispatcher: #70 session stopped: in review" in lines


def test_a_stopped_session_with_no_conversation_needs_attention_at_stop(tmp_path: Path) -> None:
    """R9, KTD5: killed before its first event, there is nothing to resume."""
    gh = FakeGitHub()
    earlier(tmp_path, gh, 70)
    boss, _, _, _ = restarted(tmp_path, gh, 0, Clock(at(15)), [])
    assert halts(tmp_path, boss) == 0
    assert moves(gh)[1:] == [(70, (NEEDS_ATTENTION,))]
    assert shown(gh, 70)[-1][0] == NEEDS_ATTENTION
    assert not record_file(tmp_path, 70).exists()


def test_stop_ends_a_session_whose_issue_left_progress_and_moves_no_label(
        tmp_path: Path) -> None:
    """KTD7: a run left it alone; stop still ends it, as nothing may run, and drops its record."""
    gh = FakeGitHub()
    pids = earlier(tmp_path, gh, 74)
    gh.answers = {}
    first, _, _, _ = restarted(tmp_path, gh, 2, Clock(at(15)), [])
    first.start()
    first.stop()
    written = list(gh.writes)
    lines: list[str] = []
    boss, _, _, killpg = restarted(tmp_path, gh, 0, Clock(at(15, 5)), lines)
    assert halts(tmp_path, boss) == 0
    assert killpg.calls == [(pids[74], signal.SIGTERM)]
    assert gh.writes == written
    assert not record_file(tmp_path, 74).exists()
    assert lines[-1] == "dispatcher: #74 is not in progress: its session ended, no label moved"


def test_stop_with_nothing_running_says_so(tmp_path: Path) -> None:
    gh = FakeGitHub()
    lines: list[str] = []
    boss, _, _, killpg = restarted(tmp_path, gh, 0, Clock(at(15)), lines)
    assert halts(tmp_path, boss) == 0
    assert lines == ["dispatcher: no dispatcher runs", "dispatcher: no session runs"]
    assert gh.writes == []
    assert killpg.calls == []


def test_stop_says_an_unreadable_record_and_leaves_it(tmp_path: Path) -> None:
    """Outside damage never crashes `stop`; the next start makes its issue need attention."""
    record_file(tmp_path, 75).parent.mkdir(parents=True)
    record_file(tmp_path, 75).write_text("{")
    gh = FakeGitHub()
    lines: list[str] = []
    boss, _, _, _ = restarted(tmp_path, gh, 0, Clock(at(15)), lines)
    assert halts(tmp_path, boss) == 0
    assert lines[-1] == (f"dispatcher: #75: its session record {record_file(tmp_path, 75)} "
                         "cannot be read")
    assert record_file(tmp_path, 75).exists()


def test_stop_that_cannot_read_github_still_ends_the_sessions_for_the_next_start(
        tmp_path: Path) -> None:
    """The records stay marked stopped: the next start pauses the issue as stopped."""
    gh = FakeGitHub()
    pids = earlier(tmp_path, gh, 70)
    writes_log(tmp_path, 70, INIT)
    gh.flaky = {"issues in progress"}
    lines: list[str] = []
    boss, _, _, killpg = restarted(tmp_path, gh, 0, Clock(at(15)), lines)
    assert halts(tmp_path, boss) == 1
    assert killpg.calls == [(pids[70], signal.SIGTERM)]
    assert moves(gh)[1:] == []
    assert json.loads(record_file(tmp_path, 70).read_text())["stopped"] is True
    assert lines[-1] == ("dispatcher: GitHub could not be read (gh issues in progress: "
                         "HTTP 502); the sessions ended, the next start judges them")
    again, _, _, _ = restarted(tmp_path, gh, 2, Clock(at(15, 5)), [], pids[70])
    again.start()
    assert moves(gh)[1:] == [(70, (PAUSED,))]
    assert dispatcher.marker_of(last_move(gh).comment or "", 70) == cause(70, STOPPED)


def test_a_session_github_cannot_be_read_for_at_stop_is_left_to_the_next_start(
        tmp_path: Path) -> None:
    """Its record stays, marked stopped; the other issues are judged."""
    gh = FakeGitHub()
    earlier(tmp_path, gh, 70, 73)
    writes_log(tmp_path, 73, INIT)
    gh.flaky = {"head"}
    lines: list[str] = []
    boss, _, _, _ = restarted(tmp_path, gh, 0, Clock(at(15)), lines)
    assert halts(tmp_path, boss) == 1
    assert ("dispatcher: #70: GitHub could not be read (gh head: HTTP 502); "
            "the next start judges it") in lines
    assert json.loads(record_file(tmp_path, 70).read_text())["stopped"] is True
    assert moves(gh)[2:] == [(73, (PAUSED,))]


def test_a_write_that_fails_at_stop_is_said_and_left_to_the_next_start(tmp_path: Path) -> None:
    """No poll follows `stop`: what still fails after one last try keeps its record."""
    gh = FakeGitHub()
    earlier(tmp_path, gh, 70)
    writes_log(tmp_path, 70, INIT)
    gh.broken = 70
    lines: list[str] = []
    boss, _, _, _ = restarted(tmp_path, gh, 0, Clock(at(15)), lines)
    assert halts(tmp_path, boss) == 1
    assert lines[-1] == "dispatcher: #70: a write failed; the next start judges it again"
    assert json.loads(record_file(tmp_path, 70).read_text())["stopped"] is True


def test_the_stop_command_runs_over_this_checkout(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    runner, _ = sessions(tmp_path, FakeGit())
    monkeypatch.setattr(dispatcher, "ROOT", tmp_path)
    monkeypatch.setattr(dispatcher, "GitHub", FakeGitHub)
    monkeypatch.setattr(dispatcher, "Sessions", lambda root: runner)
    assert dispatcher.main(["dispatcher.py", "stop"]) == 0
    assert capsys.readouterr().out.endswith(" dispatcher: no session runs\n")
    assert (tmp_path / dispatcher.STATE / "lock").exists()
