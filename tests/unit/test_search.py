"""The search session: everything about a preview search that decides anything."""

import pytest
from xedown.search import (
    MATCH_CAP,
    NO_MATCHES,
    SearchSession,
    collapse,
    status_text,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("plain", "plain"),
        ("  padded  ", "padded"),
        ("two  spaces", "two spaces"),
        ("tab\tseparated", "tab separated"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_a_query_is_collapsed_the_way_the_page_collapses_its_text(text, expected):
    # preview.js searches a flattened copy of the rendered text in which every
    # run of whitespace is one space. A query has to be collapsed the same way
    # or a phrase typed with two spaces could never match a document that
    # renders it with one.
    assert collapse(text) == expected


def test_no_live_search_has_no_label():
    assert status_text(None, -1, False) == ""


def test_no_matches_says_so_plainly():
    assert status_text(0, -1, False) == NO_MATCHES


def test_a_match_is_counted_from_one():
    assert status_text(17, 2, False) == "3 of 17"


def test_the_cap_is_shown_as_more_than_the_cap():
    assert status_text(MATCH_CAP, 2, True) == f"3 of {MATCH_CAP}+"


def test_a_fresh_session_is_not_searching():
    session = SearchSession()
    assert session.active is False
    assert session.status() == ""


def test_a_query_asks_the_page_and_a_repeat_of_it_does_not():
    session = SearchSession()
    assert session.set_query("para", False) is True
    assert session.active is True
    assert session.query == "para"
    assert session.set_query("para", False) is False
    assert session.set_query("  para  ", False) is False


def test_moving_the_case_flag_asks_the_page_again():
    session = SearchSession()
    session.set_query("para", False)
    assert session.set_query("para", True) is True
    assert session.case_sensitive is True


def test_emptying_the_query_ends_the_search():
    session = SearchSession()
    session.set_query("para", False)
    session.report(4, False, session.token)
    assert session.set_query("", False) is True
    assert session.active is False
    assert session.total is None
    assert session.status() == ""


def test_emptying_an_already_empty_query_asks_nothing():
    session = SearchSession()
    assert session.set_query("", False) is False


def test_the_case_flag_survives_an_empty_query():
    # The bar keeps its toggle and its text for the life of the tab, so the
    # session must not forget the flag the moment the entry is cleared.
    session = SearchSession()
    session.set_query("para", True)
    session.set_query("", True)
    assert session.case_sensitive is True


def test_a_fresh_search_lands_on_the_first_match():
    session = SearchSession()
    session.set_query("para", False)
    assert session.report(17, False, session.token) is True
    assert session.index == 0
    assert session.status() == "1 of 17"


def test_an_answer_for_a_replaced_query_is_ignored():
    session = SearchSession()
    session.set_query("par", False)
    stale = session.token
    session.set_query("para", False)
    assert session.report(99, False, stale) is False
    assert session.total is None


def test_a_shrinking_document_clamps_the_current_match():
    session = SearchSession()
    session.set_query("para", False)
    session.report(9, False, session.token)
    for _ in range(8):  # from the first match to the last
        session.step(True)
    assert session.status() == "9 of 9"
    session.report(6, False, session.token)
    assert session.status() == "6 of 6"


def test_losing_every_match_leaves_no_current_match():
    session = SearchSession()
    session.set_query("para", False)
    session.report(4, False, session.token)
    session.report(0, False, session.token)
    assert session.index == -1
    assert session.status() == NO_MATCHES


def test_stepping_forward_wraps_past_the_last():
    session = SearchSession()
    session.set_query("para", False)
    session.report(3, False, session.token)
    assert session.step(True) == 1
    assert session.step(True) == 2
    assert session.step(True) == 0


def test_stepping_back_wraps_past_the_first():
    session = SearchSession()
    session.set_query("para", False)
    session.report(3, False, session.token)
    assert session.index == 0
    assert session.step(False) == 2
    assert session.step(False) == 1


def test_stepping_with_no_matches_does_nothing():
    session = SearchSession()
    session.set_query("para", False)
    session.report(0, False, session.token)
    assert session.step(True) is None
    assert session.step(False) is None
    assert session.status() == NO_MATCHES


def test_the_cap_is_only_shown_when_the_page_said_it_capped():
    session = SearchSession()
    session.set_query("e", False)
    session.report(MATCH_CAP, True, session.token)
    assert session.status() == f"1 of {MATCH_CAP}+"
    session.report(MATCH_CAP, False, session.token)
    assert session.status() == f"1 of {MATCH_CAP}"


def test_clearing_ends_the_search_and_refuses_what_is_in_flight():
    session = SearchSession()
    session.set_query("para", False)
    in_flight = session.token
    session.clear()
    assert session.active is False
    assert session.total is None
    assert session.index == -1
    assert session.report(12, False, in_flight) is False
