"""Turn a place name into map coordinates, offline.

Uses the geonamescache package: 34,000 cities (population > 15,000) with latitude,
longitude, country and state, bundled with the library. No API key, no internet,
no cost - and no peer data leaves your laptop.

Lookup order, most to least precise:
  1. city   - "Fremont" + California  -> Fremont, CA (not Fremont, Ohio)
  2. region - "Morganville, NJ" (too small to be listed) -> largest city in New Jersey
  3. country - "United States" -> the capital
The result says which level matched ("precision") so the map can label it honestly.
"""
import re
from functools import lru_cache

import geonamescache

# Common shorthand people type, mapped to a name geonames knows.
ALIASES = {
    "blr": "bengaluru", "bangalore": "bengaluru", "bombay": "mumbai", "madras": "chennai",
    "nyc": "new york city", "new york": "new york city", "sf": "san francisco",
    "bay area": "san francisco", "san francisco bay": "san francisco", "silicon valley": "san jose",
    "dfw": "dallas", "dallas-fort worth": "dallas", "la": "los angeles",
    "washington dc": "washington", "washington d.c": "washington", "dc": "washington", "dmv": "washington",
    "washington dc-baltimore": "washington",
}
COUNTRY_ALIASES = {
    "usa": "US", "us": "US", "u.s.": "US", "united states of america": "US", "america": "US",
    "uk": "GB", "england": "GB", "scotland": "GB", "britain": "GB", "uae": "AE",
}
# Words around a place name that aren't part of it: "Greater Boston", "Chicago Metropolitan Area".
FILLER_RE = re.compile(
    r"^(greater|northern|southern|eastern|western|north|south|east|west|central|sunny|metro)\s+"
    r"|\s+(metropolitan area|metro area|metroplex|area|region|metro)$",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def _data():
    """Build lookup tables once (takes ~1 second), then reuse them."""
    gc = geonamescache.GeonamesCache()
    all_cities = list(gc.get_cities().values())
    cities_by_name: dict[str, list[dict]] = {}
    for city in all_cities:
        names = {city["name"]} | {n for n in city.get("alternatenames", []) if n.isascii()}
        for n in names:
            cities_by_name.setdefault(n.lower(), []).append(city)

    countries = gc.get_countries()
    country_codes = {c["name"].lower(): iso for iso, c in countries.items()}
    country_codes.update({k: v for k, v in COUNTRY_ALIASES.items()})

    states = gc.get_us_states()
    state_codes = {s["name"].lower(): code for code, s in states.items()}
    state_codes.update({code.lower(): code for code in states})
    largest_in_state = {code: _pick(all_cities, "US", code) for code in states}
    return cities_by_name, countries, country_codes, states, state_codes, largest_in_state


def _clean(name: str) -> str:
    name = name.strip().strip(".").lower()
    if name in ALIASES:  # check before stripping, so "bay area" doesn't become "bay"
        return ALIASES[name]
    name = FILLER_RE.sub("", name).strip()
    return ALIASES.get(name, name)


def _country_code(name: str | None) -> str | None:
    if not name:
        return None
    _, countries, country_codes, _, _, _ = _data()
    n = name.strip().lower()
    return n.upper() if n.upper() in countries else country_codes.get(n)


def _state_code(name: str | None) -> str | None:
    if not name:
        return None
    return _data()[4].get(_clean(name)) or _data()[4].get(name.strip().lower())


def _split_raw(raw: str) -> tuple[str | None, str | None, str | None]:
    """'Dublin, CA' / 'Morganville NJ' / 'Toronto, Canada' -> (city, region, country)."""
    raw = re.sub(r"\(.*?\)", "", raw)  # "San Ramon, California (bay area)"
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) == 1:  # "Dallas TX" / "Fremont California" - state written without a comma
        states = _data()[3]
        for state in [s["name"] for s in states.values()] + list(states):
            if parts[0].endswith(" " + state) and len(parts[0]) > len(state) + 1:
                parts = [parts[0][: -len(state)].strip(), state]
                break
    city, region, country = (parts[0] if parts else None), None, None
    for p in parts[1:]:
        if _state_code(p):  # checked before countries, so "Dublin, CA" means California, not Canada
            region = p
        elif _country_code(p):
            country = p
        else:
            region = region or p
    state_names = {s["name"].lower() for s in _data()[3].values()} - {"washington"}  # Washington: likely DC
    if city and not region and (city.lower() in state_names or
                                (_state_code(city) and not _data()[0].get(_clean(city)))):
        city, region = None, city  # "Virginia" / "New Jersey" on their own are states, not cities
    if city and not country and _country_code(city) and not _data()[0].get(_clean(city)):
        city, country = None, city  # "Australia" on its own
    return city, region, country


def _pick(candidates: list[dict], country: str | None, state: str | None) -> dict | None:
    if country:
        candidates = [c for c in candidates if c["countrycode"] == country]
    if state:
        candidates = [c for c in candidates if c["countrycode"] == "US" and c["admin1code"] == state]
    return max(candidates, key=lambda c: c["population"], default=None)


def geocode(city: str | None = None, region: str | None = None, country: str | None = None,
            raw: str | None = None) -> dict | None:
    """Best map point for a place. Returns lat, lon, city, region, country, precision - or None."""
    cities_by_name, countries, _, states, _, largest_in_state = _data()
    if raw and not (city or region or country):
        city, region, country = _split_raw(raw)

    state = _state_code(region)
    cc = _country_code(country) or ("US" if state else None)

    def result(c: dict, precision: str) -> dict:
        us_state = states.get(c["admin1code"], {}).get("name") if c["countrycode"] == "US" else None
        return {
            "lat": c["latitude"], "lon": c["longitude"], "precision": precision,
            "city": c["name"] if precision == "city" else None,
            "region": us_state if precision != "country" else None,
            "country": countries.get(c["countrycode"], {}).get("name"),
        }

    # 1. City
    if city:
        hit = _pick(cities_by_name.get(_clean(city), []), cc, state)
        if hit:
            return result(hit, "city")
        if not state and _state_code(city):  # "Northern Virginia" wasn't a city - it's a state
            state, cc = _state_code(city), cc or "US"
    # 2. Region: a US state -> its largest city; otherwise try the region as a place name
    if state:
        hit = largest_in_state.get(state)
        if hit:
            r = result(hit, "region")
            r["region"] = states[state]["name"]
            return r
    if region:
        hit = _pick(cities_by_name.get(_clean(region), []), cc, None)
        if hit:
            r = result(hit, "region")
            r["region"] = region
            return r
    # 3. Country -> capital
    if cc and cc in countries:
        hit = _pick(cities_by_name.get(countries[cc]["capital"].lower(), []), cc, None)
        if hit:
            return result(hit, "country")
    return None
