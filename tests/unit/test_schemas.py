"""Request validation rules. No database needed."""
import pytest
from pydantic import ValidationError

from app.models import TicketStatus
from app.schemas import (
    TicketCreate,
    TicketFilters,
    TicketStatusUpdate,
    TicketTriage,
    UserRegister,
)


def reg(**over):
    data = {"email": "a@b.com", "full_name": "Ada Obi", "password": "Passw0rd!"}
    return UserRegister(**{**data, **over})


def test_register_accepts_good_input_and_strips_name():
    assert reg(full_name="  Ada Obi  ").full_name == "Ada Obi"
def test_triage_requires_department_or_rejection_reason():
    assert TicketTriage(department_id=3).department_id == 3
    assert TicketTriage(reject=True, rejection_reason="Duplicate of RSV-1").reject
    with pytest.raises(ValidationError):
        TicketTriage()  # neither
    with pytest.raises(ValidationError):
        TicketTriage(reject=True)  # reject without reason
    with pytest.raises(ValidationError):
        TicketTriage(reject=True, rejection_reason="Not valid", department_id=3)  # both

@pytest.mark.parametrize("pw", ["abcdefgh", "12345678", "short1!", "a" * 129 + "1"])
def test_register_rejects_weak_or_bad_length_passwords(pw):
    with pytest.raises(ValidationError):
        reg(password=pw)


@pytest.mark.parametrize("email", ["not-an-email", "a@", "@b.com", ""])
def test_register_rejects_bad_email(email):
    with pytest.raises(ValidationError):
        reg(email=email)


def test_ticket_create_enforces_lengths_and_strips():
    t = TicketCreate(title="  Broken tap  ", description="  The tap leaks all day.  ", category_id=1)
    assert t.title == "Broken tap" and t.description == "The tap leaks all day."
    with pytest.raises(ValidationError):
        TicketCreate(title="abc", description="long enough description", category_id=1)
    with pytest.raises(ValidationError):
        TicketCreate(title="A good title", description="short", category_id=1)


def test_triage_requires_department_or_rejection_reason():
    assert TicketTriage(department_id=3).department_id == 3
    assert TicketTriage(reject=True, rejection_reason="Duplicate of RSV-1").reject
    with pytest.raises(ValidationError):
        TicketTriage()  # neither
    with pytest.raises(ValidationError):
        TicketTriage(reject=True)  # reject without reason
    with pytest.raises(ValidationError):
        TicketTriage(reject=True, rejection_reason="Not valid", department_id=3)  # both


def test_resolving_requires_a_note():
    with pytest.raises(ValidationError):
        TicketStatusUpdate(status=TicketStatus.RESOLVED)
    ok = TicketStatusUpdate(status=TicketStatus.RESOLVED, resolution_note="Fixed the pipe.")
    assert ok.resolution_note
    assert TicketStatusUpdate(status=TicketStatus.IN_PROGRESS).resolution_note is None


def test_pagination_bounds():
    assert TicketFilters().page == 1 and TicketFilters().page_size == 20
    for bad in ({"page": 0}, {"page_size": 0}, {"page_size": 101}):
        with pytest.raises(ValidationError):
            TicketFilters(**bad)
