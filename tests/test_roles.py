"""Tests for core/roles.py - grouping job titles into families."""
import math

from core.roles import role_family


def test_role_families():
    assert role_family("Lead AI Engineer") == "AI & ML"
    assert role_family("Senior Data & ML Platform Engineer") == "AI & ML"
    assert role_family("Data Consultant") == "Data"
    assert role_family("Senior Product Manager") == "Product & Program"
    assert role_family("Solutions Architect and Technical Lead") == "Architecture"
    assert role_family("Engineering Leader") == "Leadership"
    assert role_family("Senior SDET / QA Automation Engineer") == "Quality & Testing"
    assert role_family("Staff Software Engineer") == "Software Engineering"
    assert role_family("Chef") == "Other"


def test_missing_role():
    assert role_family(None) is None
    assert role_family(math.nan) is None  # how pandas passes an empty cell
