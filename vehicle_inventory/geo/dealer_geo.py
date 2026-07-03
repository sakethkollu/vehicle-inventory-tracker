"""Dealer geocoding cache for state/ZIP-based inventory filters."""

from __future__ import annotations

import json
import logging
import html
import re
import threading
import time
import urllib.parse
import urllib.request
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from vehicle_inventory.db.backend import DbConnection, DbRow, commit_with_retry, execute_with_retry

from geopy.geocoders import Nominatim

from vehicle_inventory.db.sql_compat import haversine_miles_sql

logger = logging.getLogger(__name__)

US_STATE_NAME_TO_CODE: Dict[str, str] = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "District of Columbia": "DC",
    "Florida": "FL",
    "Georgia": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
}

US_STATE_CODE_TO_NAME = {code: name for name, code in US_STATE_NAME_TO_CODE.items()}

GeoTuple = Tuple[float, float, str, str, str]
ProgressCallback = Callable[[int, int, str], None]

_geocoder: Optional[Nominatim] = None
_zip_coords_cache: Dict[str, Tuple[float, float]] = {}
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_nominatim_lock = threading.Lock()
_nominatim_min_interval_sec = 1.1
_nominatim_last_request_at = 0.0
_playwright_lock = threading.Lock()
_google_maps_lock = threading.Lock()
_google_maps_min_interval_sec = 2.5
_google_maps_last_request_at = 0.0

_CLOUDFLARE_MARKERS = (
    "client challenge",
    "cf-browser-verification",
    "challenge-platform",
    "just a moment",
    "enable javascript and cookies",
    "checking your browser",
    "cloudflare",
)


def configure_nominatim_rate_limit(seconds: float) -> None:
    global _nominatim_min_interval_sec
    _nominatim_min_interval_sec = max(0.0, float(seconds))


@contextmanager
def _nominatim_request_slot():
    global _nominatim_last_request_at
    with _nominatim_lock:
        if _nominatim_min_interval_sec > 0:
            elapsed = time.monotonic() - _nominatim_last_request_at
            wait = _nominatim_min_interval_sec - elapsed
            if wait > 0:
                time.sleep(wait)
        try:
            yield
        finally:
            _nominatim_last_request_at = time.monotonic()


@contextmanager
def _google_maps_request_slot():
    global _google_maps_last_request_at
    with _google_maps_lock:
        if _google_maps_min_interval_sec > 0:
            elapsed = time.monotonic() - _google_maps_last_request_at
            wait = _google_maps_min_interval_sec - elapsed
            if wait > 0:
                time.sleep(wait)
        try:
            yield
        finally:
            _google_maps_last_request_at = time.monotonic()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_geocoder() -> Nominatim:
    global _geocoder
    if _geocoder is None:
        _geocoder = Nominatim(user_agent="vehicle-inventory-tracker-dealer-geo/1.1")
    return _geocoder


def normalize_us_zip(value: str) -> Optional[str]:
    if not value:
        return None
    digits = re.sub(r"\D", "", value.strip())
    if len(digits) >= 5:
        return digits[:5]
    return None


def _geocode_zip_query(query: str) -> Optional[Tuple[float, float]]:
    geocoder = get_geocoder()
    try:
        with _nominatim_request_slot():
            loc = geocoder.geocode(query, addressdetails=True, country_codes="us", timeout=8.0)
    except Exception as exc:
        logger.debug("Nominatim ZIP error for %r: %s", query, exc)
        return None
    if not loc:
        return None
    return float(loc.latitude), float(loc.longitude)


def _zip_geocode_query_candidates(zip_code: str) -> List[str]:
    normalized = normalize_us_zip(zip_code)
    if not normalized:
        return []
    return [
        f"{normalized}, USA",
        f"{normalized}, United States",
        normalized,
    ]


def _nominatim_zip_coords(zip_code: str) -> Optional[Tuple[float, float]]:
    normalized = normalize_us_zip(zip_code)
    if not normalized:
        return None
    geocoder = get_geocoder()
    structured_queries = [
        {"postalcode": normalized, "countrycodes": "us"},
        {"postalcode": normalized, "country": "United States"},
    ]
    for query in structured_queries:
        try:
            with _nominatim_request_slot():
                loc = geocoder.geocode(query, addressdetails=True, timeout=8.0)
        except Exception as exc:
            logger.debug("Nominatim structured ZIP error for %r: %s", query, exc)
            continue
        if loc:
            return float(loc.latitude), float(loc.longitude)
    for query in _zip_geocode_query_candidates(normalized):
        coords = _geocode_zip_query(query)
        if coords is not None:
            return coords
    return None


def _zippopotam_us_zip_coords(zip_code: str) -> Optional[Tuple[float, float]]:
    normalized = normalize_us_zip(zip_code)
    if not normalized:
        return None
    url = f"https://api.zippopotam.us/us/{normalized}"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.debug("Zippopotam ZIP error for %r: %s", zip_code, exc)
        return None
    places = data.get("places") or []
    if not places:
        return None
    place = places[0]
    try:
        return float(place["latitude"]), float(place["longitude"])
    except (KeyError, TypeError, ValueError):
        return None


def _zippopotam_us_place(zip_code: str) -> Optional[Tuple[str, str]]:
    normalized = normalize_us_zip(zip_code)
    if not normalized:
        return None
    url = f"https://api.zippopotam.us/us/{normalized}"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.debug("Zippopotam place error for %r: %s", zip_code, exc)
        return None
    places = data.get("places") or []
    if not places:
        return None
    place = places[0]
    city = (place.get("place name") or "").strip()
    state = normalize_state_code(place.get("state abbreviation"))
    if not city or not state:
        return None
    return city, state


def _photon_zip_coords(zip_code: str) -> Optional[Tuple[float, float]]:
    normalized = normalize_us_zip(zip_code)
    if not normalized:
        return None
    queries = _zip_geocode_query_candidates(normalized)
    for query in queries:
        params = urllib.parse.urlencode({"q": query, "limit": 12})
        url = f"https://photon.komoot.io/api/?{params}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.debug("Photon ZIP error for %r: %s", query, exc)
            continue

        for feature in data.get("features") or []:
            props = feature.get("properties") or {}
            if (props.get("countrycode") or "").upper() != "US":
                continue
            postcode = normalize_us_zip(props.get("postcode") or "")
            if postcode != normalized:
                continue
            coords = feature.get("geometry", {}).get("coordinates") or []
            if len(coords) < 2:
                continue
            return float(coords[1]), float(coords[0])
    return None


def geocode_postal_code(zip_code: str) -> Optional[Tuple[float, float]]:
    normalized = normalize_us_zip(zip_code)
    if not normalized:
        return None
    cached = _zip_coords_cache.get(normalized)
    if cached is not None:
        return cached

    coords = _nominatim_zip_coords(normalized)
    if coords is None:
        coords = _zippopotam_us_zip_coords(normalized)
    if coords is None:
        coords = _photon_zip_coords(normalized)
    if coords is not None:
        _zip_coords_cache[normalized] = coords
    return coords


def reverse_geocode_postal_code(lat: float, lng: float) -> Optional[str]:
    geo = _nominatim_reverse_geo(lat, lng)
    if not geo:
        return None
    return normalize_us_zip(geo[2]) or None


def _nominatim_reverse_geo(lat: float, lng: float) -> Optional[GeoTuple]:
    geocoder = get_geocoder()
    try:
        with _nominatim_request_slot():
            loc = geocoder.reverse((lat, lng), exactly_one=True, timeout=8.0)
    except Exception as exc:
        logger.debug("Nominatim reverse error for (%s, %s): %s", lat, lng, exc)
        return None
    if not loc:
        return None
    addr = (loc.raw or {}).get("address") or {}
    state = _state_from_nominatim_addr(addr)
    if not state:
        return None
    return (
        float(lat),
        float(lng),
        addr.get("postcode") or "",
        _city_from_nominatim_addr(addr),
        state,
    )


def ensure_dealer_geo_cache_table(conn: DbConnection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dealer_geo_cache (
            dealer_cd TEXT PRIMARY KEY,
            query_text TEXT,
            latitude REAL,
            longitude REAL,
            postal_code TEXT,
            city TEXT,
            state TEXT,
            geocoded_at TEXT NOT NULL
        )
        """
    )


def clear_dealer_geo_cache(conn: DbConnection) -> int:
    ensure_dealer_geo_cache_table(conn)
    conn.execute("DELETE FROM dealer_geo_cache")
    conn.commit()
    return int(getattr(conn, "rowcount", 0) or 0)


def normalize_state_code(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    upper = cleaned.upper()
    if len(upper) == 2 and upper.isalpha():
        return upper
    title = cleaned.title()
    return US_STATE_NAME_TO_CODE.get(title)


def state_label(state_code: str) -> str:
    code = normalize_state_code(state_code) or state_code
    return US_STATE_CODE_TO_NAME.get(code, code)


def expand_state_filter_values(state_codes: List[str]) -> List[str]:
    values: set[str] = set()
    for raw in state_codes:
        code = normalize_state_code(raw)
        if code:
            values.add(code)
            full_name = US_STATE_CODE_TO_NAME.get(code)
            if full_name:
                values.add(full_name)
        elif raw:
            cleaned = raw.strip()
            if cleaned:
                values.add(cleaned)
                title = cleaned.title()
                mapped = US_STATE_NAME_TO_CODE.get(title)
                if mapped:
                    values.add(mapped)
                values.add(title)
    return sorted(values)


def _has_valid_geo(row: Optional[DbRow]) -> bool:
    if row is None:
        return False
    if row["latitude"] is None or row["longitude"] is None:
        return False
    return normalize_state_code(row["state"]) is not None


def _state_from_nominatim_addr(addr: Dict[str, str]) -> Optional[str]:
    state = normalize_state_code(addr.get("state"))
    if state:
        return state
    iso = addr.get("ISO3166-2-lvl4") or ""
    if iso.startswith("US-"):
        return normalize_state_code(iso[3:])
    return None


def _city_from_nominatim_addr(addr: Dict[str, str]) -> str:
    for key in ("city", "town", "village", "hamlet", "municipality"):
        value = addr.get(key)
        if value:
            return value
    return ""


def _iter_jsonld_nodes(data) -> Iterable[dict]:
    if isinstance(data, dict):
        yield data
        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_jsonld_nodes(item)
    elif isinstance(data, list):
        for item in data:
            yield from _iter_jsonld_nodes(item)


def _normalize_postal_address(raw: dict) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    state = normalize_state_code(raw.get("addressRegion") or raw.get("state"))
    city = (raw.get("addressLocality") or raw.get("city") or "").strip()
    postal = (raw.get("postalCode") or raw.get("postcode") or "").strip()
    street = (raw.get("streetAddress") or raw.get("street") or "").strip()
    if not state and not postal and not city:
        return None
    return {
        "streetAddress": street,
        "addressLocality": city,
        "addressRegion": state or "",
        "postalCode": postal,
    }


def _parse_autodealer_address_from_html(html_text: str) -> Optional[dict]:
    for block in re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html_text,
        flags=re.S | re.I,
    ):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for item in _iter_jsonld_nodes(data):
            item_type = str(item.get("@type") or "").lower()
            if item_type not in {"autodealer", "localbusiness", "organization", "store"}:
                continue
            address = item.get("address")
            if isinstance(address, dict):
                normalized = _normalize_postal_address(address)
                if normalized:
                    return normalized

    fields = {}
    for key, pattern in (
        ("streetAddress", r'"streetAddress"\s*:\s*"([^"]+)"'),
        ("addressLocality", r'"addressLocality"\s*:\s*"([^"]+)"'),
        ("addressRegion", r'"addressRegion"\s*:\s*"([^"]+)"'),
        ("postalCode", r'"postalCode"\s*:\s*"([^"]+)"'),
    ):
        match = re.search(pattern, html_text)
        if match:
            fields[key] = match.group(1).strip()
    return _normalize_postal_address(fields) if fields else None


def _is_cloudflare_challenge(html_text: str) -> bool:
    lowered = (html_text or "").lower()
    if not lowered:
        return True
    return any(marker in lowered for marker in _CLOUDFLARE_MARKERS)


def _fetch_url_html_urllib(url: str) -> Optional[str]:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": _BROWSER_USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        logger.debug("Website fetch failed for %s: %s", url, exc)
        return None


def _fetch_url_html_playwright(url: str, *, timeout_ms: int = 30000) -> Optional[str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.debug("Playwright unavailable for dealer website fetch: %s", url)
        return None

    with _playwright_lock:
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    context = browser.new_context(user_agent=_BROWSER_USER_AGENT)
                    page = context.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    page.wait_for_timeout(2500)
                    return page.content()
                finally:
                    browser.close()
        except Exception as exc:
            logger.debug("Playwright website fetch failed for %s: %s", url, exc)
            return None


def _fetch_autodealer_address(website: str) -> Tuple[Optional[dict], str]:
    if not website:
        return None, ""
    url = website.strip()
    if not url.startswith("http"):
        url = f"https://{url.lstrip('/')}"

    html_text = _fetch_url_html_urllib(url)
    if html_text:
        address = _parse_autodealer_address_from_html(html_text)
        if address:
            return address, "urllib"
        if not _is_cloudflare_challenge(html_text):
            return None, ""

    html_text = _fetch_url_html_playwright(url)
    if not html_text:
        return None, ""
    address = _parse_autodealer_address_from_html(html_text)
    if address:
        return address, "playwright"
    return None, ""


def _slugify_place(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def _parse_toyota_com_dealer_page(html_text: str) -> Optional[dict]:
    match = re.search(r'data-address="(\{.*?\})"', html_text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    state = normalize_state_code(payload.get("state"))
    postal = normalize_us_zip(payload.get("zipcode") or payload.get("zip") or "")
    city = (payload.get("city") or "").strip()
    if postal and not state:
        place = _zippopotam_us_place(postal)
        if place:
            city = city or place[0]
            state = place[1]
    return _normalize_postal_address(
        {
            "streetAddress": payload.get("address") or "",
            "addressLocality": city,
            "addressRegion": state or "",
            "postalCode": postal or "",
        }
    )


def _fetch_toyota_com_dealer_address(
    dealer_name: str,
    *,
    city: str = "",
    state: str = "",
    postal_code: str = "",
) -> Optional[dict]:
    slug = _slugify_place(dealer_name)
    if not slug:
        return None

    state_code = normalize_state_code(state) or ""
    city_name = (city or "").strip()
    zip_code = normalize_us_zip(postal_code) or ""
    if zip_code and not state_code:
        place = _zippopotam_us_place(zip_code)
        if place:
            city_name = city_name or place[0]
            state_code = place[1]

    urls: List[str] = []
    if state_code and city_name and zip_code:
        city_slug = _slugify_place(city_name)
        urls.append(
            f"https://www.toyota.com/dealers/{state_code.lower()}/{city_slug}/{zip_code}/{slug}/"
        )
    if state_code and city_name:
        city_slug = _slugify_place(city_name)
        urls.append(f"https://www.toyota.com/dealers/{state_code.lower()}/{city_slug}/{slug}/")

    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_USER_AGENT})
            with urllib.request.urlopen(req, timeout=12) as resp:
                html_text = html.unescape(resp.read().decode("utf-8", errors="ignore"))
        except Exception as exc:
            logger.debug("Toyota.com dealer page fetch failed for %s: %s", url, exc)
            continue
        address = _parse_toyota_com_dealer_page(html_text)
        if address:
            return address
    return None


def _try_toyota_com_geocode(
    dealer_name: str,
    hint_geo: Optional[GeoTuple],
) -> Optional[Tuple[str, GeoTuple]]:
    if not hint_geo:
        return None
    _lat, _lon, postal, city, state = hint_geo
    address = _fetch_toyota_com_dealer_address(
        dealer_name,
        city=city,
        state=state,
        postal_code=postal,
    )
    if not address:
        return None
    return _geo_from_postal_address(address, f"toyota.com:{dealer_name}")


_GENERIC_PLACE_TOKENS = frozenset(
    {
        "downtown",
        "north",
        "south",
        "east",
        "west",
        "central",
        "metro",
        "greater",
        "area",
        "county",
        "uptown",
        "midtown",
        "auto",
        "mall",
        "plaza",
        "parkway",
    }
)


def _dealer_name_tokens(dealer_name: str) -> List[str]:
    cleaned = (dealer_name or "").lower()
    for token in (
        "toyota",
        "mazda",
        "of",
        "the",
        "and",
        "motor",
        "motors",
        "sales",
        "inc",
        "llc",
    ):
        cleaned = cleaned.replace(token, " ")
    return [token for token in re.split(r"\W+", cleaned) if len(token) >= 3]


def _dealer_brand_label(dealer_name: str) -> str:
    lowered = (dealer_name or "").lower()
    if "mazda" in lowered:
        return "Mazda"
    if "toyota" in lowered:
        return "Toyota"
    return "auto"


def _distinctive_dealer_tokens(dealer_name: str) -> List[str]:
    tokens = _dealer_name_tokens(dealer_name)
    distinctive = [token for token in tokens if token not in _GENERIC_PLACE_TOKENS]
    return distinctive or tokens


def _extract_dealer_place(dealer_name: str) -> str:
    name = (dealer_name or "").strip()
    for pattern in (
        r"(?i)toyota of (.+)",
        r"(?i)mazda of (.+)",
        r"(?i)toyota on (.+)",
        r"(?i).+ toyota of (.+)",
        r"(?i).+ mazda of (.+)",
    ):
        match = re.match(pattern, name)
        if match:
            return match.group(1).strip()
    return ""


def _place_validation_tokens(dealer_name: str) -> List[str]:
    place = _extract_dealer_place(dealer_name)
    if not place:
        return []
    tokens = _dealer_name_tokens(place)
    return [token for token in tokens if token not in _GENERIC_PLACE_TOKENS]


def _dealer_geo_matches_name(dealer_name: str, geo: GeoTuple) -> bool:
    place_tokens = _place_validation_tokens(dealer_name)
    if not place_tokens:
        return True
    _lat, _lon, postal, city, state = geo
    haystack = f"{city} {state} {postal}".lower()
    return all(token in haystack for token in place_tokens)


def _dealer_query_candidates(
    dealer_name: str,
    dealer_website: str = "",
    city_hint: str = "",
) -> List[str]:
    name = (dealer_name or "").strip()
    queries: List[str] = []
    seen: set[str] = set()

    def add(query: str) -> None:
        cleaned = query.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            queries.append(cleaned)

    if name:
        add(name)
        add(f"{name}, USA")
    place = _extract_dealer_place(name)
    brand = _dealer_brand_label(name)
    if place:
        add(f"{place}, USA")
        add(f"{brand}, {place}, USA")
        add(f"{brand} dealership, {place}, USA")
    if city_hint:
        add(f"{name}, {city_hint}, USA")
        add(f"{brand} dealership, {city_hint}, USA")
        add(f"{city_hint}, USA")
    if name:
        add(f"{name}, {brand} dealership, USA")
    if dealer_website:
        add(dealer_website)
    return queries


def _nominatim_geocode_query(query: str) -> Optional[GeoTuple]:
    geocoder = get_geocoder()
    try:
        with _nominatim_request_slot():
            loc = geocoder.geocode(query, addressdetails=True, country_codes="us", timeout=8.0)
    except Exception as exc:
        logger.debug("Nominatim error for %r: %s", query, exc)
        return None
    if not loc:
        return None
    raw = loc.raw or {}
    addr = raw.get("address") or {}
    state = _state_from_nominatim_addr(addr)
    if not state:
        return None
    return (
        float(loc.latitude),
        float(loc.longitude),
        addr.get("postcode") or "",
        _city_from_nominatim_addr(addr),
        state,
    )


def _geo_from_postal_address(address: dict, query_prefix: str) -> Optional[Tuple[str, GeoTuple]]:
    street = address.get("streetAddress") or ""
    city = address.get("addressLocality") or ""
    state = normalize_state_code(address.get("addressRegion"))
    postal = address.get("postalCode") or ""
    if not state and not postal:
        return None

    queries: List[str] = []
    if street and city and state and postal:
        queries.append(f"{street}, {city}, {state} {postal}, USA")
    if city and state and postal:
        queries.append(f"{postal}, {city}, {state}, USA")
        queries.append(f"{city}, {state} {postal}, USA")
    if city and state:
        queries.append(f"{city}, {state}, USA")
    if postal and state:
        queries.append(f"{postal}, {state}, USA")

    for query in queries:
        geo = _nominatim_geocode_query(query)
        if geo:
            lat, lon, found_postal, found_city, found_state = geo
            return (
                f"{query_prefix} | {query}",
                (
                    lat,
                    lon,
                    found_postal or postal,
                    found_city or city,
                    found_state or state or "",
                ),
            )
    return None


def _photon_geocode_query(
    query: str,
    *,
    dealer_name: str = "",
    require_name_match: bool = False,
) -> Optional[GeoTuple]:
    params = urllib.parse.urlencode({"q": query, "limit": 12})
    url = f"https://photon.komoot.io/api/?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.debug("Photon error for %r: %s", query, exc)
        return None

    place_tokens = _place_validation_tokens(dealer_name) if require_name_match else []
    dealer_tokens = _dealer_name_tokens(dealer_name) if require_name_match else []
    for feature in data.get("features") or []:
        props = feature.get("properties") or {}
        if (props.get("countrycode") or "").upper() != "US":
            continue
        coords = feature.get("geometry", {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        state = normalize_state_code(props.get("state"))
        if not state:
            continue
        city = props.get("city") or props.get("town") or ""
        postal = props.get("postcode") or ""
        geo = (
            float(coords[1]),
            float(coords[0]),
            postal,
            city,
            state,
        )
        if require_name_match:
            poi_name = str(props.get("name") or "").lower()
            lowered_name = (dealer_name or "").lower()
            if "toyota" in lowered_name and "toyota" not in poi_name:
                continue
            if "mazda" in lowered_name and "mazda" not in poi_name:
                continue
            if place_tokens:
                if not _dealer_geo_matches_name(dealer_name, geo):
                    continue
            elif dealer_tokens:
                haystack = " ".join(
                    str(props.get(key) or "")
                    for key in ("name", "city", "town", "street", "locality", "district")
                ).lower()
                if not any(token in haystack for token in dealer_tokens):
                    continue
        return geo
    return None


def _photon_hint_geo(dealer_name: str, query: str) -> Optional[GeoTuple]:
    params = urllib.parse.urlencode({"q": query, "limit": 12})
    url = f"https://photon.komoot.io/api/?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.debug("Photon hint error for %r: %s", query, exc)
        return None

    place_tokens = _place_validation_tokens(dealer_name)
    dealer_tokens = _dealer_name_tokens(dealer_name)
    best_geo: Optional[GeoTuple] = None
    best_score = -1

    for feature in data.get("features") or []:
        props = feature.get("properties") or {}
        if (props.get("countrycode") or "").upper() != "US":
            continue
        coords = feature.get("geometry", {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        state = normalize_state_code(props.get("state"))
        if not state:
            continue
        city = props.get("city") or props.get("town") or ""
        postal = props.get("postcode") or ""
        poi_name = str(props.get("name") or "").lower()
        haystack = " ".join(
            str(props.get(key) or "")
            for key in ("name", "city", "town", "street", "locality", "district", "postcode", "state")
        ).lower()
        score = 0
        for token in place_tokens:
            if token in haystack:
                score += 8
        for token in dealer_tokens:
            if token in haystack:
                score += 3
        if "toyota" in poi_name and "toyota" in (dealer_name or "").lower():
            score += 5
        if "mazda" in poi_name and "mazda" in (dealer_name or "").lower():
            score += 5
        if score > best_score:
            best_score = score
            best_geo = (
                float(coords[1]),
                float(coords[0]),
                postal,
                city,
                state,
            )

    return best_geo if best_score > 0 else None


_GOOGLE_MAPS_COORD_PATTERNS = (
    re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)"),
    re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)"),
    re.compile(r'"center":\{"lat":(-?\d+\.\d+),"lng":(-?\d+\.\d+)\}'),
    re.compile(
        r'"latitude"\s*:\s*(-?\d+\.\d+)[^}]{0,120}?"longitude"\s*:\s*(-?\d+\.\d+)'
    ),
)


def _is_plausible_us_coords(lat: float, lng: float) -> bool:
    return 24.0 <= lat <= 50.0 and -125.0 <= lng <= -66.0


def parse_google_maps_coords(text: str) -> Optional[Tuple[float, float]]:
    """Extract lat/lng from a Google Maps URL or HTML payload."""
    if not text:
        return None
    for pattern in _GOOGLE_MAPS_COORD_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        lat = float(match.group(1))
        lng = float(match.group(2))
        if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
            return lat, lng
    return None


def _dismiss_google_maps_consent(page) -> None:
    for selector in (
        'button:has-text("Accept all")',
        'button:has-text("Reject all")',
        'button[aria-label="Accept all"]',
        'button[aria-label="Reject all"]',
    ):
        try:
            locator = page.locator(selector)
            if locator.count() > 0:
                locator.first.click(timeout=1500)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def _google_maps_search_coords_playwright(query: str) -> Optional[Tuple[float, float]]:
    """Search Google Maps in a headless browser and read coordinates from the result URL/HTML."""
    cleaned = (query or "").strip()
    if not cleaned:
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.debug("Playwright unavailable for Google Maps fallback: %r", query)
        return None

    search_url = f"https://www.google.com/maps/search/{urllib.parse.quote(cleaned)}"
    with _playwright_lock:
        with _google_maps_request_slot():
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    try:
                        context = browser.new_context(
                            user_agent=_BROWSER_USER_AGENT,
                            locale="en-US",
                        )
                        page = context.new_page()
                        page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
                        _dismiss_google_maps_consent(page)
                        for _ in range(6):
                            coords = parse_google_maps_coords(page.url)
                            if coords and _is_plausible_us_coords(*coords):
                                return coords
                            html_text = page.content()
                            coords = parse_google_maps_coords(html_text)
                            if coords and _is_plausible_us_coords(*coords):
                                return coords
                            page.wait_for_timeout(1000)
                    finally:
                        browser.close()
            except Exception as exc:
                logger.debug("Google Maps search failed for %r: %s", query, exc)
                return None
    return None


def _google_maps_geocode_query(query: str, *, dealer_name: str = "") -> Optional[GeoTuple]:
    coords = _google_maps_search_coords_playwright(query)
    if not coords:
        return None
    lat, lng = coords
    geo = _nominatim_reverse_geo(lat, lng)
    if not geo:
        return None
    if dealer_name and not _dealer_geo_matches_name(dealer_name, geo):
        return None
    return geo


def _is_preferred_geo_query(query_text: str) -> bool:
    text = (query_text or "").strip()
    return (
        text.startswith("website")
        or text.startswith("photon:")
        or text.startswith("toyota.com:")
        or text.startswith("oem:")
    )


def _preferred_geo_query_sql(column: str = "dgc.query_text") -> str:
    col = f"TRIM(COALESCE({column}, ''))"
    return f"""(
            {col} LIKE 'website%'
            OR {col} LIKE 'photon:%'
            OR {col} LIKE 'toyota.com:%'
            OR {col} LIKE 'oem:%'
          )"""


def geocode_dealer_record(
    dealer_name: str,
    dealer_website: str = "",
    *,
    city_hint: str = "",
) -> Tuple[str, Optional[GeoTuple]]:
    """Return (query_text, geo_tuple_or_none) for a dealer."""
    if dealer_website:
        address, fetch_source = _fetch_autodealer_address(dealer_website)
        if address:
            query_prefix = (
                f"website+playwright:{dealer_website}"
                if fetch_source == "playwright"
                else f"website:{dealer_website}"
            )
            website_result = _geo_from_postal_address(address, query_prefix)
            if website_result:
                return website_result

    candidates = _dealer_query_candidates(dealer_name, dealer_website, city_hint)
    attempted: List[str] = []

    hint_geo: Optional[GeoTuple] = None
    for query in candidates[:6]:
        hint_geo = _photon_hint_geo(dealer_name, query)
        if hint_geo:
            break
    if hint_geo:
        tcom_result = _try_toyota_com_geocode(dealer_name, hint_geo)
        if tcom_result:
            return tcom_result

    for query in candidates:
        label = f"photon:{query}"
        attempted.append(label)
        geo = _photon_geocode_query(
            query,
            dealer_name=dealer_name,
            require_name_match=True,
        )
        if geo:
            return label, geo

    for query in candidates:
        attempted.append(query)
        geo = _nominatim_geocode_query(query)
        if geo and _dealer_geo_matches_name(dealer_name, geo):
            return query, geo

    google_attempted: List[str] = []
    for query in candidates[:4]:
        label = f"googlemaps:{query}"
        google_attempted.append(label)
        geo = _google_maps_geocode_query(query, dealer_name=dealer_name)
        if geo:
            return label, geo

    combined = attempted + google_attempted
    if combined:
        return " | ".join(combined[:8]), None
    return dealer_name or dealer_website or "unknown", None


def geocode_dealer_by_cd(
    conn: DbConnection,
    dealer_cd: str,
    *,
    city_hint: str = "",
    delay_sec: float = 0,
) -> bool:
    row = conn.execute(
        """
        SELECT dealer_cd, dealer_marketing_name, dealer_website
        FROM dealers
        WHERE dealer_cd = ?
        """,
        (dealer_cd,),
    ).fetchone()
    if not row:
        return False
    dealer_name = row["dealer_marketing_name"] or dealer_cd
    dealer_website = row["dealer_website"] or ""
    query, geo = geocode_dealer_record(dealer_name, dealer_website, city_hint=city_hint)
    success = _store_dealer_geo(conn, dealer_cd, query, geo)
    conn.commit()
    if delay_sec > 0:
        time.sleep(delay_sec)
    return success


def normalize_cached_states(conn: DbConnection) -> int:
    ensure_dealer_geo_cache_table(conn)
    rows = conn.execute(
        """
        SELECT dealer_cd, state
        FROM dealer_geo_cache
        WHERE COALESCE(state, '') != ''
        """
    ).fetchall()
    updated = 0
    for row in rows:
        code = normalize_state_code(row["state"])
        if code and code != row["state"]:
            conn.execute(
                "UPDATE dealer_geo_cache SET state = ? WHERE dealer_cd = ?",
                (code, row["dealer_cd"]),
            )
            updated += 1
    if updated:
        conn.commit()
    return updated


def dealer_geo_stats(conn: DbConnection) -> Dict[str, int]:
    ensure_dealer_geo_cache_table(conn)
    # Count all synced dealers, not only those with vehicle_runs rows (Mazda nationwide
    # dealer sync populates dealers before any inventory ingest).
    total = conn.execute(
        """
        SELECT COUNT(DISTINCT d.dealer_cd) AS total
        FROM dealers d
        """
    ).fetchone()
    geocoded = conn.execute(
        """
        SELECT COUNT(DISTINCT d.dealer_cd) AS total
        FROM dealers d
        JOIN dealer_geo_cache dgc ON dgc.dealer_cd = d.dealer_cd
        WHERE dgc.latitude IS NOT NULL
          AND COALESCE(dgc.state, '') != ''
        """
    ).fetchone()
    preferred = conn.execute(
        f"""
        SELECT COUNT(DISTINCT d.dealer_cd) AS total
        FROM dealers d
        JOIN dealer_geo_cache dgc ON dgc.dealer_cd = d.dealer_cd
        WHERE dgc.latitude IS NOT NULL
          AND COALESCE(dgc.state, '') != ''
          AND LENGTH(TRIM(COALESCE(dgc.state, ''))) <= 2
          AND {_preferred_geo_query_sql()}
        """
    ).fetchone()
    total_count = int(total["total"]) if total else 0
    geocoded_count = int(geocoded["total"]) if geocoded else 0
    preferred_count = int(preferred["total"]) if preferred else 0
    return {
        "dealers_in_inventory": total_count,
        "geocoded": geocoded_count,
        "preferred_geocoded": preferred_count,
        "remaining": max(0, total_count - geocoded_count),
    }


def _fetch_dealers_needing_geocode(
    conn: DbConnection, limit: Optional[int]
) -> List[DbRow]:
    ensure_dealer_geo_cache_table(conn)
    sql = """
        SELECT d.dealer_cd, d.dealer_marketing_name, d.dealer_website
        FROM dealers d
        WHERE (
            NOT EXISTS (
                SELECT 1 FROM dealer_geo_cache dgc WHERE dgc.dealer_cd = d.dealer_cd
            )
            OR EXISTS (
                SELECT 1
                FROM dealer_geo_cache dgc
                WHERE dgc.dealer_cd = d.dealer_cd
                  AND (
                    dgc.latitude IS NULL
                    OR dgc.longitude IS NULL
                    OR COALESCE(dgc.state, '') = ''
                    OR LENGTH(TRIM(COALESCE(dgc.state, ''))) > 2
                  )
            )
        )
        ORDER BY d.dealer_cd
    """
    params: List = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(limit, 0))
    return conn.execute(sql, params).fetchall()


def _fetch_all_inventory_dealers(
    conn: DbConnection, limit: Optional[int]
) -> List[DbRow]:
    ensure_dealer_geo_cache_table(conn)
    sql = """
        SELECT d.dealer_cd, d.dealer_marketing_name, d.dealer_website
        FROM dealers d
        ORDER BY d.dealer_cd
    """
    params: List = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(limit, 0))
    return conn.execute(sql, params).fetchall()


def _store_dealer_geo(
    conn: DbConnection,
    dealer_cd: str,
    query: str,
    geo: Optional[GeoTuple],
) -> bool:
    if geo:
        lat, lon, postal_code, city, state = geo
        execute_with_retry(
            conn,
            """
            INSERT OR REPLACE INTO dealer_geo_cache (
                dealer_cd, query_text, latitude, longitude, postal_code, city, state, geocoded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (dealer_cd, query, lat, lon, postal_code or "", city or "", state or "", utc_now()),
        )
        return normalize_state_code(state) is not None
    execute_with_retry(
        conn,
        """
        INSERT OR REPLACE INTO dealer_geo_cache (
            dealer_cd, query_text, latitude, longitude, postal_code, city, state, geocoded_at
        ) VALUES (?, ?, NULL, NULL, NULL, NULL, NULL, ?)
        """,
        (dealer_cd, query, utc_now()),
    )
    return False


def store_dealer_geo_coordinates(
    conn: DbConnection,
    dealer_cd: str,
    *,
    latitude: float,
    longitude: float,
    postal_code: str = "",
    city: str = "",
    state: str = "",
    query_text: str = "",
) -> None:
    """Persist known coordinates (e.g. from OEM dealer API) without external geocoding."""
    ensure_dealer_geo_cache_table(conn)
    query = query_text or f"{city}, {state} {postal_code}".strip(", ")
    if query and not query.startswith("oem:"):
        query = f"oem:{query}"
    _store_dealer_geo(
        conn,
        dealer_cd,
        query,
        (latitude, longitude, postal_code, city, state),
    )


def _geocode_dealer_row(row: DbRow) -> Tuple[str, str, str, Optional[GeoTuple], Optional[str]]:
    dealer_cd = row["dealer_cd"]
    dealer_name = row["dealer_marketing_name"] or dealer_cd
    dealer_website = row["dealer_website"] or ""
    try:
        query, geo = geocode_dealer_record(dealer_name, dealer_website)
        return dealer_cd, dealer_name, query, geo, None
    except Exception as exc:
        logger.exception("Geocode failed for dealer %s: %s", dealer_cd, exc)
        return dealer_cd, dealer_name, f"error:{dealer_name}", None, str(exc)


async def _geocode_all_dealers_async(
    conn: DbConnection,
    rows: List[DbRow],
    *,
    progress_callback: Optional[ProgressCallback] = None,
    workers: int = 8,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Tuple[int, int]:
    total = len(rows)
    geocoded = 0
    failed = 0
    worker_count = max(1, int(workers))
    semaphore = asyncio.Semaphore(worker_count)

    async def run_row(row: DbRow):
        async with semaphore:
            return await asyncio.to_thread(_geocode_dealer_row, row)

    tasks = [asyncio.create_task(run_row(row)) for row in rows]
    completed = 0
    for task in asyncio.as_completed(tasks):
        if should_cancel and should_cancel():
            for pending in tasks:
                if not pending.done():
                    pending.cancel()
            break
        dealer_cd, dealer_name, query, geo, error = await task
        completed += 1
        if progress_callback:
            progress_callback(completed, total, dealer_cd)
        if error:
            failed += 1
        else:
            try:
                if _store_dealer_geo(conn, dealer_cd, query, geo):
                    geocoded += 1
                else:
                    failed += 1
            except Exception as exc:
                logger.exception("Failed to store geocode for dealer %s: %s", dealer_cd, exc)
                failed += 1
        if completed % 10 == 0 or completed == total:
            commit_with_retry(conn)
    commit_with_retry(conn)
    return geocoded, failed


def geocode_all_dealers(
    conn: DbConnection,
    *,
    limit: Optional[int] = None,
    delay_sec: float = 1.1,
    progress_callback: Optional[ProgressCallback] = None,
    force: bool = False,
    workers: int = 1,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Dict[str, int]:
    normalize_cached_states(conn)
    configure_nominatim_rate_limit(delay_sec)
    fetch = _fetch_all_inventory_dealers if force else _fetch_dealers_needing_geocode
    rows = fetch(conn, limit)
    total = len(rows)
    geocoded = 0
    failed = 0
    worker_count = max(1, int(workers))

    if worker_count == 1:
        for index, row in enumerate(rows, start=1):
            if should_cancel and should_cancel():
                break
            dealer_cd, dealer_name, query, geo, error = _geocode_dealer_row(row)
            if progress_callback:
                progress_callback(index, total, dealer_cd)
            if error:
                failed += 1
            else:
                try:
                    if _store_dealer_geo(conn, dealer_cd, query, geo):
                        geocoded += 1
                    else:
                        failed += 1
                except Exception as exc:
                    logger.exception("Failed to store geocode for dealer %s: %s", dealer_cd, exc)
                    failed += 1
            commit_with_retry(conn)
            if index < total and delay_sec > 0:
                time.sleep(delay_sec)
    else:
        geocoded, failed = asyncio.run(
            _geocode_all_dealers_async(
                conn,
                rows,
                progress_callback=progress_callback,
                workers=worker_count,
                should_cancel=should_cancel,
            )
        )
    stats = dealer_geo_stats(conn)
    return {
        "processed": total,
        "batch_geocoded": geocoded,
        "batch_failed": failed,
        **stats,
    }


def geocode_missing_dealers(conn: DbConnection, limit: int = 20) -> int:
    result = geocode_all_dealers(conn, limit=limit, delay_sec=1.1)
    return int(result.get("batch_geocoded", 0))


def _haversine_miles_exists_sql(vr_alias: str) -> str:
    miles = haversine_miles_sql("?", "?")
    return f"""
    EXISTS (
        SELECT 1
        FROM dealer_geo_cache dgc
        WHERE dgc.dealer_cd = {vr_alias}.dealer_cd
          AND dgc.latitude IS NOT NULL
          AND dgc.longitude IS NOT NULL
          AND ({miles}) {{op}} ?
    )
    """


def _run_distance_bound_sql(vr_alias: str, op: str) -> str:
    return f"{vr_alias}.distance IS NOT NULL AND {vr_alias}.distance {op} ?"


MAX_DEALER_GEO_DISPLAY_MILES = 500


def dealer_display_distance_sql(
    haversine_miles_expr: str,
    *,
    vr_alias: str = "vr",
) -> str:
    """Prefer OEM ingest distance for labels; geocoded miles are fallback only."""
    return f"""
        COALESCE(
            MIN({vr_alias}.distance),
            MIN(
                CASE
                    WHEN dgc.latitude IS NOT NULL AND dgc.longitude IS NOT NULL THEN
                        ({haversine_miles_expr})
                END
            )
        ) AS distance_miles
    """


def normalize_dealer_display_distance(distance_miles: Optional[float]) -> Optional[float]:
    if distance_miles is None:
        return None
    value = float(distance_miles)
    if value > MAX_DEALER_GEO_DISPLAY_MILES:
        return None
    return round(value, 1)


def _append_distance_max_filter(
    where: List[str],
    params: List,
    *,
    vr_alias: str,
    distance_max: int,
    search_coords: Optional[Tuple[float, float]] = None,
) -> None:
    if search_coords:
        lat, lng = search_coords
        haversine = _haversine_miles_exists_sql(vr_alias).format(op="<=")
        oem = _run_distance_bound_sql(vr_alias, "<=")
        where.append(f"(({haversine}) OR ({oem}))")
        params.extend([lat, lng, lat, int(distance_max), int(distance_max)])
        return
    where.append(_run_distance_bound_sql(vr_alias, "<="))
    params.append(int(distance_max))


def _append_distance_min_filter(
    where: List[str],
    params: List,
    *,
    vr_alias: str,
    distance_min: int,
    search_coords: Optional[Tuple[float, float]] = None,
) -> None:
    if search_coords:
        lat, lng = search_coords
        haversine = _haversine_miles_exists_sql(vr_alias).format(op=">=")
        oem = _run_distance_bound_sql(vr_alias, ">=")
        where.append(f"(({haversine}) OR ({oem}))")
        params.extend([lat, lng, lat, int(distance_min), int(distance_min)])
        return
    where.append(_run_distance_bound_sql(vr_alias, ">="))
    params.append(int(distance_min))


def append_run_location_filters(
    where: List[str],
    params: List,
    *,
    distance_max: Optional[int] = None,
    distance_min: Optional[int] = None,
    state_codes: Optional[List[str]] = None,
    search_zip: Optional[str] = None,
    vr_alias: str = "vr",
) -> None:
    normalized_states = expand_state_filter_values(state_codes or []) if state_codes else []
    apply_distance = not normalized_states

    if apply_distance:
        normalized_zip = normalize_us_zip(search_zip or "")
        search_coords = geocode_postal_code(normalized_zip) if normalized_zip else None

        if normalized_zip:
            if distance_max is not None or distance_min is not None:
                if search_coords is None:
                    logger.warning(
                        "Search ZIP %s could not be geocoded; using OEM distance only",
                        normalized_zip,
                    )
                if distance_max is not None:
                    _append_distance_max_filter(
                        where,
                        params,
                        vr_alias=vr_alias,
                        distance_max=int(distance_max),
                        search_coords=search_coords,
                    )
                if distance_min is not None:
                    _append_distance_min_filter(
                        where,
                        params,
                        vr_alias=vr_alias,
                        distance_min=int(distance_min),
                        search_coords=search_coords,
                    )
        elif distance_max is not None or distance_min is not None:
            if distance_max is not None:
                _append_distance_max_filter(
                    where,
                    params,
                    vr_alias=vr_alias,
                    distance_max=int(distance_max),
                )
            if distance_min is not None:
                _append_distance_min_filter(
                    where,
                    params,
                    vr_alias=vr_alias,
                    distance_min=int(distance_min),
                )

    if normalized_states:
        placeholders = ",".join("?" for _ in normalized_states)
        where.append(
            f"""
            EXISTS (
                SELECT 1
                FROM dealer_geo_cache dgc
                WHERE dgc.dealer_cd = {vr_alias}.dealer_cd
                  AND TRIM(COALESCE(dgc.state, '')) IN ({placeholders})
            )
            """
        )
        params.extend(normalized_states)
