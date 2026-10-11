"""Tests for core/geo.py - offline city lookup."""
import pytest

from core.geo import geocode


@pytest.mark.parametrize("raw, city, region, country, precision", [
    ("Dublin, CA", "Dublin", "California", "United States", "city"),       # California, not Ireland/Canada
    ("Fremont California", "Fremont", "California", "United States", "city"),
    ("Dallas TX", "Dallas", "Texas", "United States", "city"),
    ("BLR", "Bengaluru", None, "India", "city"),
    ("Bangalore, India", "Bengaluru", None, "India", "city"),
    ("bay area", "San Francisco", "California", "United States", "city"),
    ("Greater Chicago", "Chicago", "Illinois", "United States", "city"),
    ("Morganville NJ", None, "New Jersey", "United States", "region"),    # too small -> state
    ("Northern Virginia, USA", None, "Virginia", "United States", "region"),
    ("Virginia", None, "Virginia", "United States", "region"),
    ("Australia", None, None, "Australia", "country"),
])
def test_geocode_raw_text(raw, city, region, country, precision):
    g = geocode(raw=raw)
    assert (g["city"], g["region"], g["country"], g["precision"]) == (city, region, country, precision)


def test_structured_input_from_claude():
    g = geocode(city="Mississauga", region="Ontario", country="Canada")
    assert g["city"] == "Mississauga" and g["precision"] == "city"
    assert -80 < g["lon"] < -79


def test_unknown_place_returns_none():
    assert geocode(raw="Middle of nowhere") is None
