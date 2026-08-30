"""Destination place resolution helpers (misspellings + ambiguous names).

Pure domain logic: decide whether the traveller must confirm a place before we
plan. Providers (Nominatim / mocks) and optional LLM fallback supply candidates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any


@dataclass(frozen=True)
class PlaceCandidate:
    city: str | None
    country: str | None
    label: str

    def key(self) -> tuple[str, str]:
        return ((self.city or "").strip().lower(), (self.country or "").strip().lower())


_PLACE_TYPES = frozenset(
    {
        "city",
        "town",
        "village",
        "municipality",
        "hamlet",
        "suburb",
        "neighbourhood",
        "neighborhood",
        "state",
        "province",
        "region",
        "country",
        "administrative",
    }
)


def destination_query(*, city: str | None, country: str | None) -> str:
    parts = [p.strip() for p in (city, country) if p and str(p).strip()]
    return ", ".join(parts)


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _similar(a: str | None, b: str | None) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def candidate_from_nominatim(raw: dict[str, Any]) -> PlaceCandidate | None:
    """Build a place candidate from a Nominatim jsonv2 + addressdetails hit."""
    addr = raw.get("address") if isinstance(raw.get("address"), dict) else {}
    place_type = str(raw.get("type") or raw.get("addresstype") or "").lower()
    cls = str(raw.get("class") or "").lower()
    if cls not in {"place", "boundary", "administrative"} and place_type not in _PLACE_TYPES:
        # Still allow if address has a clear city/country (some hits are noisy).
        if not (addr.get("city") or addr.get("town") or addr.get("country")):
            return None

    city = (
        addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("municipality")
        or addr.get("state")  # e.g. city-state / region-as-destination
    )
    country = addr.get("country")
    if place_type == "country" or (not city and country):
        city = None
        country = country or (raw.get("name") if place_type == "country" else country)

    display = str(raw.get("display_name") or raw.get("name") or "").strip()
    if not city and not country:
        if not display:
            return None
        # Fallback: first comma segment as label only.
        parts = [p.strip() for p in display.split(",") if p.strip()]
        city = parts[0] if parts else None
        country = parts[-1] if len(parts) > 1 else None

    label_parts = [p for p in (city, country) if p]
    label = ", ".join(label_parts) if label_parts else display
    if not label:
        return None
    return PlaceCandidate(
        city=str(city).strip() if city else None,
        country=str(country).strip() if country else None,
        label=label,
    )


def dedupe_candidates(candidates: list[PlaceCandidate], *, limit: int = 5) -> list[PlaceCandidate]:
    seen: set[tuple[str, str]] = set()
    out: list[PlaceCandidate] = []
    for c in candidates:
        key = c.key()
        if key in seen or key == ("", ""):
            continue
        seen.add(key)
        out.append(c)
        if len(out) >= limit:
            break
    return out


def evaluate_destination(
    *,
    user_city: str | None,
    user_country: str | None,
    candidates: list[PlaceCandidate],
) -> dict[str, Any]:
    """Decide auto-confirm vs ask the user.

    Returns a dict with:
    - ``needs_confirmation`` (bool)
    - ``reason``: ``ok`` | ``not_found`` | ``possible_typo`` | ``ambiguous``
    - ``message`` (user-facing)
    - ``canonical_city`` / ``canonical_country`` when we can normalize without asking
    - ``candidates`` (serialisable list)
    """
    cleaned = dedupe_candidates(candidates)
    serialised = [
        {"city": c.city, "country": c.country, "label": c.label} for c in cleaned
    ]
    user_label = destination_query(city=user_city, country=user_country) or "that place"

    if not cleaned:
        return {
            "needs_confirmation": True,
            "reason": "not_found",
            "message": (
                f"I couldn't find a clear match for \"{user_label}\". "
                "Could you double-check the spelling, or name the city and country?"
            ),
            "canonical_city": user_city,
            "canonical_country": user_country,
            "candidates": [],
        }

    # Same short name used as both a city and a country (or multiple countries).
    countries = {(_norm(c.country) or "") for c in cleaned if c.country}
    cities = {(_norm(c.city) or "") for c in cleaned if c.city}
    user_token = _norm(user_city) or _norm(user_country)
    city_country_clash = bool(
        user_token
        and any(_norm(c.city) == user_token for c in cleaned)
        and any(_norm(c.country) == user_token for c in cleaned)
    )

    if len(cleaned) > 1 and (len(countries) > 1 or len(cities) > 1 or city_country_clash):
        options = "; ".join(f"{i + 1}) {c.label}" for i, c in enumerate(cleaned[:5]))
        return {
            "needs_confirmation": True,
            "reason": "ambiguous",
            "message": (
                f"Just to be sure — \"{user_label}\" could mean a few places. "
                f"Which one did you mean? {options} "
                "(reply with a number or the full place name.)"
            ),
            "canonical_city": user_city,
            "canonical_country": user_country,
            "candidates": serialised,
        }

    best = cleaned[0]
    city_score = max(_similar(user_city, best.city), _similar(user_country, best.city))
    country_score = max(_similar(user_country, best.country), _similar(user_city, best.country))
    # Strong match on city, or country-only trips.
    if user_city and city_score >= 0.86:
        return {
            "needs_confirmation": False,
            "reason": "ok",
            "message": "",
            "canonical_city": best.city or user_city,
            "canonical_country": best.country or user_country,
            "candidates": serialised,
        }
    if not user_city and user_country and country_score >= 0.86:
        return {
            "needs_confirmation": False,
            "reason": "ok",
            "message": "",
            "canonical_city": best.city,
            "canonical_country": best.country or user_country,
            "candidates": serialised,
        }

    # Close but not exact → likely typo / alternate spelling.
    if max(city_score, country_score) >= 0.55:
        return {
            "needs_confirmation": True,
            "reason": "possible_typo",
            "message": (
                f"Did you mean **{best.label}** (you wrote \"{user_label}\")? "
                "Reply yes to use that, or tell me the correct city and country."
            ),
            "canonical_city": best.city or user_city,
            "canonical_country": best.country or user_country,
            "candidates": serialised,
        }

    options = "; ".join(f"{i + 1}) {c.label}" for i, c in enumerate(cleaned[:5]))
    return {
        "needs_confirmation": True,
        "reason": "ambiguous",
        "message": (
            f"I found a few places near \"{user_label}\". Which fits? {options}"
        ),
        "canonical_city": user_city,
        "canonical_country": user_country,
        "candidates": serialised,
    }


def apply_destination_answer(
    answer: Any,
    *,
    candidates: list[dict[str, Any]],
    fallback_city: str | None,
    fallback_country: str | None,
) -> tuple[str | None, str | None]:
    """Map a HITL resume payload onto city/country."""
    if isinstance(answer, dict):
        if answer.get("city") or answer.get("country"):
            return (
                (str(answer["city"]).strip() if answer.get("city") else fallback_city),
                (
                    str(answer["country"]).strip()
                    if answer.get("country")
                    else fallback_country
                ),
            )
        if "index" in answer and candidates:
            try:
                idx = int(answer["index"])
                pick = candidates[idx]
                return pick.get("city") or fallback_city, pick.get("country") or fallback_country
            except (TypeError, ValueError, IndexError):
                pass
        text = str(
            answer.get("feedback") or answer.get("answer") or answer.get("action") or ""
        ).strip()
    else:
        text = str(answer or "").strip()

    if not text:
        if candidates:
            pick = candidates[0]
            return pick.get("city") or fallback_city, pick.get("country") or fallback_country
        return fallback_city, fallback_country

    lower = text.lower()
    if lower in {"yes", "y", "ok", "okay", "sure", "correct", "confirm", "approved"}:
        if candidates:
            pick = candidates[0]
            return pick.get("city") or fallback_city, pick.get("country") or fallback_country
        return fallback_city, fallback_country

    # Numeric pick: "1", "2)"
    m = re.match(r"^(\d+)\s*[).:]?\s*$", text.strip())
    if m and candidates:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(candidates):
            pick = candidates[idx]
            return pick.get("city") or fallback_city, pick.get("country") or fallback_country

    # Match a candidate label loosely.
    for pick in candidates:
        label = str(pick.get("label") or "")
        if _norm(label) and _norm(label) in _norm(text):
            return pick.get("city") or fallback_city, pick.get("country") or fallback_country
        if _similar(text, label) >= 0.8:
            return pick.get("city") or fallback_city, pick.get("country") or fallback_country

    # Free-text "City, Country"
    parts = [p.strip() for p in re.split(r"[,/|]", text) if p.strip()]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    if parts:
        # Single token — treat as city unless it clearly matches a candidate country.
        token = parts[0]
        for pick in candidates:
            if _similar(token, pick.get("country")) >= 0.9 and not pick.get("city"):
                return None, pick.get("country")
        return token, fallback_country
    return fallback_city, fallback_country
