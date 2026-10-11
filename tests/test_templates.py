"""Tests for core/templates.py."""
import math

from core.templates import DEFAULT_TEMPLATE, fill, unknown_variables

PEER = {"name": "Priya Raman", "role": "Data Scientist", "city": "Pune", "company": "Helix"}


def test_fill_default_template():
    note = fill(DEFAULT_TEMPLATE, PEER, "Rajiv", "Mastering AI class, October cohort")
    assert note == ("Hi Priya, I'm Rajiv from the Mastering AI class, October cohort. "
                    "Great to find a fellow Data Scientist in Pune. Would love to connect!")


def test_fallbacks_for_missing_details():
    peer = {"name": math.nan, "discord_handle": "moe_k", "role": None, "city": None, "country": "UAE"}
    note = fill("Hi {first_name}, fellow {role} in {city}", peer, "Rajiv", "x")
    assert note == "Hi moe_k, fellow classmate in UAE"


def test_unknown_variables_are_reported():
    assert unknown_variables("Hi {frist_name} from {city}") == ["frist_name"]
