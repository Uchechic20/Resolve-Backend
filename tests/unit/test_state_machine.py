"""The ticket status table and the one function allowed to change status."""
from types import SimpleNamespace

import pytest

from app.exceptions import InvalidTransitionError
from app.models import TicketStatus as S
from app.services.ticket_service import (
    AGENT_TARGETS,
    ALLOWED_TRANSITIONS,
    ASSIGNABLE,
    TERMINAL,
    TRANSFERABLE,
    TicketService,
)


def test_every_status_has_an_entry():
    assert set(ALLOWED_TRANSITIONS) == set(S)


def test_terminal_states_have_no_exits():
    assert TERMINAL == {S.CLOSED, S.REJECTED}
    for status in TERMINAL:
        assert ALLOWED_TRANSITIONS[status] == set()


def test_every_state_is_reachable_from_submitted():
    seen, todo = {S.SUBMITTED}, [S.SUBMITTED]
    while todo:
        for nxt in ALLOWED_TRANSITIONS[todo.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    assert seen == set(S)


def test_no_state_transitions_to_itself():
    for status, targets in ALLOWED_TRANSITIONS.items():
        assert status not in targets


def test_agents_cannot_pick_routing_or_reopen_states():
    """Triage, claim, transfer and reopen have dedicated, permission-checked actions."""
    assert AGENT_TARGETS == {S.IN_PROGRESS, S.RESOLVED, S.CLOSED}
    for hidden in (S.SUBMITTED, S.TRIAGED, S.ASSIGNED, S.REJECTED, S.REOPENED):
        assert hidden not in AGENT_TARGETS


def test_helper_sets_only_contain_workable_states():
    assert not (ASSIGNABLE & TERMINAL)
    assert not (TRANSFERABLE & TERMINAL)
    assert S.SUBMITTED not in ASSIGNABLE | TRANSFERABLE  # intake has no department


@pytest.mark.parametrize(
    "old,new",
    [
        (S.SUBMITTED, S.TRIAGED),
        (S.SUBMITTED, S.REJECTED),
        (S.TRIAGED, S.ASSIGNED),
        (S.ASSIGNED, S.IN_PROGRESS),
        (S.IN_PROGRESS, S.RESOLVED),
        (S.RESOLVED, S.CLOSED),
        (S.RESOLVED, S.REOPENED),
        (S.REOPENED, S.IN_PROGRESS),
    ],
)
def test_set_status_allows_valid_moves(old, new):
    ticket = SimpleNamespace(status=old)
    assert TicketService._set_status(ticket, new) == old
    assert ticket.status == new


@pytest.mark.parametrize(
    "old,new",
    [
        (S.SUBMITTED, S.RESOLVED),
        (S.SUBMITTED, S.ASSIGNED),
        (S.TRIAGED, S.RESOLVED),
        (S.ASSIGNED, S.RESOLVED),
        (S.IN_PROGRESS, S.CLOSED),
        (S.CLOSED, S.REOPENED),
        (S.REJECTED, S.TRIAGED),
        (S.RESOLVED, S.IN_PROGRESS),
    ],
)
def test_set_status_blocks_invalid_moves_and_leaves_ticket_untouched(old, new):
    ticket = SimpleNamespace(status=old)
    with pytest.raises(InvalidTransitionError):
        TicketService._set_status(ticket, new)
    assert ticket.status == old


def test_setting_the_same_status_is_a_noop():
    ticket = SimpleNamespace(status=S.ASSIGNED)
    assert TicketService._set_status(ticket, S.ASSIGNED) == S.ASSIGNED
    assert ticket.status == S.ASSIGNED
