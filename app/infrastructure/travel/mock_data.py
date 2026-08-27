"""Curated offline travel fixtures for ``TRAVEL_MOCK_APIS`` (Stage 10).

Seven demo destinations. Unknown cities return ``None`` from the mock adapters
so specialists fall back to web search. Knowledge-base builds are unaffected —
these fixtures only feed hotels / flights / places / transit providers.
"""

from __future__ import annotations

import re
from typing import Any, TypedDict


class CityFixture(TypedDict):
    key: str
    display_name: str
    country: str
    center: tuple[float, float]  # lat, lng
    aliases: list[str]
    hotels: list[dict[str, Any]]
    flights: list[dict[str, Any]]
    pois: list[dict[str, Any]]  # attractions + restaurants (food uses restaurant category)


_CITIES: list[CityFixture] = [
    {
        "key": "london",
        "display_name": "London",
        "country": "United Kingdom",
        "center": (51.5074, -0.1278),
        "aliases": ["london", "london uk", "london england"],
        "hotels": [
            {
                "name": "The Bloomsbury Hotel",
                "area": "Bloomsbury",
                "nightly_rate_usd": 220,
                "lat": 51.5225,
                "lng": -0.1280,
                "notes": "Central, near British Museum; mid-range classic.",
            },
            {
                "name": "Premier Inn Waterloo",
                "area": "South Bank",
                "nightly_rate_usd": 140,
                "lat": 51.5030,
                "lng": -0.1120,
                "notes": "Budget-friendly near Waterloo Station and the Thames.",
            },
            {
                "name": "The Ned",
                "area": "City of London",
                "nightly_rate_usd": 380,
                "lat": 51.5136,
                "lng": -0.0900,
                "notes": "Upscale former bank HQ; rooftop and multiple restaurants.",
            },
        ],
        "flights": [
            {
                "summary": "JFK → LHR, direct, ~7h",
                "price_usd": 650,
                "details": (
                    "British Airways / Virgin; Heathrow Terminal 5. "
                    "Heathrow Express ~15 min to Paddington."
                ),
            },
            {
                "summary": "CDG → LHR, direct, ~1h 15m",
                "price_usd": 120,
                "details": "EasyJet / BA short-haul; also Eurostar alternative (~2h 20m).",
            },
            {
                "summary": "Local transit: Oyster / contactless + Tube",
                "price_usd": 45,
                "details": (
                    "Weekly Travelcard Zones 1-2 ~GBP 45. "
                    "Tube + buses cover most sightseeing."
                ),
            },
        ],
        "pois": [
            {
                "name": "British Museum",
                "category": "museum",
                "lat": 51.5194,
                "lng": -0.1270,
                "estimated_duration_min": 150,
                "notes": "Free entry; book timed slots for popular galleries.",
            },
            {
                "name": "Tower of London",
                "category": "landmark",
                "lat": 51.5081,
                "lng": -0.0759,
                "estimated_duration_min": 120,
                "notes": "Crown Jewels; combine with Tower Bridge walk.",
            },
            {
                "name": "South Bank Walk",
                "category": "neighborhood",
                "lat": 51.5070,
                "lng": -0.1150,
                "estimated_duration_min": 90,
                "notes": "London Eye, Tate Modern, Borough Market nearby.",
            },
            {
                "name": "Borough Market",
                "category": "restaurant",
                "lat": 51.5055,
                "lng": -0.0910,
                "estimated_duration_min": 60,
                "notes": "Food hall classics — Monmouth Coffee, Neal's Yard Dairy.",
            },
            {
                "name": "Dishoom Covent Garden",
                "category": "restaurant",
                "lat": 51.5124,
                "lng": -0.1268,
                "estimated_duration_min": 75,
                "notes": "Bombay café; expect a queue or book ahead.",
            },
        ],
    },
    {
        "key": "paris",
        "display_name": "Paris",
        "country": "France",
        "center": (48.8566, 2.3522),
        "aliases": ["paris", "paris france"],
        "hotels": [
            {
                "name": "Hôtel des Arts Montmartre",
                "area": "Montmartre",
                "nightly_rate_usd": 160,
                "lat": 48.8867,
                "lng": 2.3431,
                "notes": "Charming mid-range near Sacré-Cœur.",
            },
            {
                "name": "Generator Paris",
                "area": "10th Arrondissement",
                "nightly_rate_usd": 90,
                "lat": 48.8789,
                "lng": 2.3580,
                "notes": "Budget hostel/hotel hybrid near Gare de l'Est.",
            },
            {
                "name": "Le Meurice",
                "area": "1st Arrondissement",
                "nightly_rate_usd": 750,
                "lat": 48.8650,
                "lng": 2.3280,
                "notes": "Palace hotel facing the Tuileries.",
            },
        ],
        "flights": [
            {
                "summary": "JFK → CDG, direct, ~7h 30m",
                "price_usd": 620,
                "details": "Air France / Delta; RER B ~35 min to central Paris.",
            },
            {
                "summary": "LHR → CDG, direct, ~1h 15m",
                "price_usd": 110,
                "details": "Or Eurostar London-Paris (~2h 20m) into Gare du Nord.",
            },
            {
                "summary": "Local transit: Navigo / Metro",
                "price_usd": 40,
                "details": "Navigo Decouverte weekly pass covers Metro/RER/bus in zones 1-5.",
            },
        ],
        "pois": [
            {
                "name": "Louvre Museum",
                "category": "museum",
                "lat": 48.8606,
                "lng": 2.3376,
                "estimated_duration_min": 180,
                "notes": "Book timed entry; focus on a wing to avoid overload.",
            },
            {
                "name": "Eiffel Tower",
                "category": "landmark",
                "lat": 48.8584,
                "lng": 2.2945,
                "estimated_duration_min": 120,
                "notes": "Summit tickets sell out; Champ de Mars picnic alternative.",
            },
            {
                "name": "Le Marais",
                "category": "neighborhood",
                "lat": 48.8575,
                "lng": 2.3588,
                "estimated_duration_min": 120,
                "notes": "Place des Vosges, Jewish quarter, boutiques.",
            },
            {
                "name": "Bouillon Chartier",
                "category": "restaurant",
                "lat": 48.8720,
                "lng": 2.3435,
                "estimated_duration_min": 60,
                "notes": "Classic bouillon prices; shared tables, no reservations.",
            },
            {
                "name": "Du Pain et des Idées",
                "category": "restaurant",
                "lat": 48.8710,
                "lng": 2.3625,
                "estimated_duration_min": 30,
                "notes": "Iconic bakery near Canal Saint-Martin.",
            },
        ],
    },
    {
        "key": "rome",
        "display_name": "Rome",
        "country": "Italy",
        "center": (41.9028, 12.4964),
        "aliases": ["rome", "roma", "rome italy", "roma italy"],
        "hotels": [
            {
                "name": "Hotel Artemide",
                "area": "Via Nazionale",
                "nightly_rate_usd": 200,
                "lat": 41.9010,
                "lng": 12.4935,
                "notes": "Mid-range between Termini and the historic centre.",
            },
            {
                "name": "The Beehive",
                "area": "Termini",
                "nightly_rate_usd": 95,
                "lat": 41.9018,
                "lng": 12.5040,
                "notes": "Budget-friendly near the main station.",
            },
            {
                "name": "Hotel de Russie",
                "area": "Piazza del Popolo",
                "nightly_rate_usd": 650,
                "lat": 41.9105,
                "lng": 12.4760,
                "notes": "Luxury garden hotel near Villa Borghese.",
            },
        ],
        "flights": [
            {
                "summary": "JFK -> FCO, 1 stop, ~10-12h",
                "price_usd": 580,
                "details": "Leonardo Express train FCO → Termini ~32 min.",
            },
            {
                "summary": "CDG → FCO, direct, ~2h",
                "price_usd": 95,
                "details": "Alitalia / EasyJet; Ciampino (CIA) is budget-carrier alternative.",
            },
            {
                "summary": "Local transit: Roma Pass + Metro",
                "price_usd": 35,
                "details": "Metro A/B cover Colosseum, Vatican area (bus/walk for historic core).",
            },
        ],
        "pois": [
            {
                "name": "Colosseum",
                "category": "landmark",
                "lat": 41.8902,
                "lng": 12.4922,
                "estimated_duration_min": 120,
                "notes": "Combine with Roman Forum / Palatine Hill ticket.",
            },
            {
                "name": "Vatican Museums",
                "category": "museum",
                "lat": 41.9065,
                "lng": 12.4536,
                "estimated_duration_min": 180,
                "notes": "Book early; exit into St. Peter's Square.",
            },
            {
                "name": "Trastevere",
                "category": "neighborhood",
                "lat": 41.8897,
                "lng": 12.4695,
                "estimated_duration_min": 120,
                "notes": "Evening stroll and trattorie across the Tiber.",
            },
            {
                "name": "Da Enzo al 29",
                "category": "restaurant",
                "lat": 41.8885,
                "lng": 12.4680,
                "estimated_duration_min": 75,
                "notes": "Trastevere trattoria; arrive early or expect a wait.",
            },
            {
                "name": "Pizzarium Bonci",
                "category": "restaurant",
                "lat": 41.9068,
                "lng": 12.4465,
                "estimated_duration_min": 40,
                "notes": "Pizza al taglio near the Vatican.",
            },
        ],
    },
    {
        "key": "berlin",
        "display_name": "Berlin",
        "country": "Germany",
        "center": (52.5200, 13.4050),
        "aliases": ["berlin", "berlin germany"],
        "hotels": [
            {
                "name": "Circus Hotel",
                "area": "Mitte",
                "nightly_rate_usd": 150,
                "lat": 52.5295,
                "lng": 13.4010,
                "notes": "Design mid-range near Rosenthaler Platz.",
            },
            {
                "name": "Generator Berlin Mitte",
                "area": "Oranienburger Straße",
                "nightly_rate_usd": 80,
                "lat": 52.5255,
                "lng": 13.3930,
                "notes": "Budget hostel/hotel near Museum Island.",
            },
            {
                "name": "Hotel Adlon Kempinski",
                "area": "Unter den Linden",
                "nightly_rate_usd": 520,
                "lat": 52.5163,
                "lng": 13.3800,
                "notes": "Iconic luxury facing the Brandenburg Gate.",
            },
        ],
        "flights": [
            {
                "summary": "JFK → BER, 1 stop, ~10h",
                "price_usd": 540,
                "details": "Berlin Brandenburg (BER); S-Bahn ~30-40 min to Alexanderplatz.",
            },
            {
                "summary": "LHR → BER, direct, ~1h 45m",
                "price_usd": 100,
                "details": "easyJet / BA; dense short-haul network across Europe.",
            },
            {
                "summary": "Local transit: BVG Tageskarte",
                "price_usd": 25,
                "details": "AB day ticket covers U-Bahn, S-Bahn, tram, bus.",
            },
        ],
        "pois": [
            {
                "name": "Brandenburg Gate",
                "category": "landmark",
                "lat": 52.5163,
                "lng": 13.3777,
                "estimated_duration_min": 45,
                "notes": "Pair with Reichstag dome (free timed booking).",
            },
            {
                "name": "Museum Island",
                "category": "museum",
                "lat": 52.5169,
                "lng": 13.4010,
                "estimated_duration_min": 180,
                "notes": "Pergamon / Neues Museum; Museum Pass recommended.",
            },
            {
                "name": "Kreuzberg",
                "category": "neighborhood",
                "lat": 52.4980,
                "lng": 13.4180,
                "estimated_duration_min": 120,
                "notes": "Street food, street art, canal walks.",
            },
            {
                "name": "Mustafa's Gemüse Kebap",
                "category": "restaurant",
                "lat": 52.4938,
                "lng": 13.3885,
                "estimated_duration_min": 30,
                "notes": "Legendary street kebab; long queues common.",
            },
            {
                "name": "Zur letzten Instanz",
                "category": "restaurant",
                "lat": 52.5178,
                "lng": 13.4155,
                "estimated_duration_min": 75,
                "notes": "One of Berlin's oldest inns; German classics.",
            },
        ],
    },
    {
        "key": "new_york",
        "display_name": "New York",
        "country": "United States",
        "center": (40.7128, -74.0060),
        "aliases": [
            "new york",
            "new york city",
            "nyc",
            "newyork",
            "new york usa",
        ],
        "hotels": [
            {
                "name": "Pod 51",
                "area": "Midtown East",
                "nightly_rate_usd": 160,
                "lat": 40.7557,
                "lng": -73.9690,
                "notes": "Compact mid-range rooms; good transit access.",
            },
            {
                "name": "HI New York City Hostel",
                "area": "Upper West Side",
                "nightly_rate_usd": 70,
                "lat": 40.7985,
                "lng": -73.9670,
                "notes": "Budget near Central Park and the museums.",
            },
            {
                "name": "The Plaza",
                "area": "Fifth Avenue",
                "nightly_rate_usd": 850,
                "lat": 40.7645,
                "lng": -73.9740,
                "notes": "Landmark luxury overlooking Central Park South.",
            },
        ],
        "flights": [
            {
                "summary": "LHR → JFK, direct, ~8h",
                "price_usd": 700,
                "details": "Also EWR / LGA; AirTrain + subway into Manhattan.",
            },
            {
                "summary": "LAX → JFK, direct, ~5h 30m",
                "price_usd": 280,
                "details": "Multiple daily flights; JetBlue / Delta / AA.",
            },
            {
                "summary": "Local transit: MetroCard / OMNY",
                "price_usd": 34,
                "details": "7-day Unlimited MetroCard; subway + bus citywide.",
            },
        ],
        "pois": [
            {
                "name": "Central Park",
                "category": "attraction",
                "lat": 40.7829,
                "lng": -73.9654,
                "estimated_duration_min": 120,
                "notes": "Enter at 59th St; Bethesda Fountain and The Mall.",
            },
            {
                "name": "Metropolitan Museum of Art",
                "category": "museum",
                "lat": 40.7794,
                "lng": -73.9632,
                "estimated_duration_min": 180,
                "notes": "Pay-what-you-wish for NY residents; others timed tickets.",
            },
            {
                "name": "Lower Manhattan / Financial District",
                "category": "neighborhood",
                "lat": 40.7075,
                "lng": -74.0113,
                "estimated_duration_min": 120,
                "notes": "9/11 Memorial, Wall Street, ferry to Statue of Liberty.",
            },
            {
                "name": "Katz's Delicatessen",
                "category": "restaurant",
                "lat": 40.7223,
                "lng": -73.9874,
                "estimated_duration_min": 45,
                "notes": "Pastrami on rye institution on the Lower East Side.",
            },
            {
                "name": "Joe's Pizza (Carmine St)",
                "category": "restaurant",
                "lat": 40.7306,
                "lng": -74.0022,
                "estimated_duration_min": 30,
                "notes": "Classic NYC slice in the West Village.",
            },
        ],
    },
    {
        "key": "damascus",
        "display_name": "Damascus",
        "country": "Syria",
        "center": (33.5138, 36.2765),
        "aliases": [
            "damascus",
            "damascus syria",
            "dimashq",
            "الشام",
        ],
        "hotels": [
            {
                "name": "Beit Al Wali",
                "area": "Old City",
                "nightly_rate_usd": 110,
                "lat": 33.5115,
                "lng": 36.3065,
                "notes": "Restored Damascene house near Bab Sharqi.",
            },
            {
                "name": "Four Seasons Damascus",
                "area": "Abu Rummaneh",
                "nightly_rate_usd": 280,
                "lat": 33.5205,
                "lng": 36.2880,
                "notes": "Modern luxury outside the Old City walls.",
            },
            {
                "name": "Talisman Hotel",
                "area": "Old City",
                "nightly_rate_usd": 95,
                "lat": 33.5098,
                "lng": 36.3100,
                "notes": "Boutique courtyard hotel in the historic quarter.",
            },
        ],
        "flights": [
            {
                "summary": "IST → DAM, direct, ~2h",
                "price_usd": 180,
                "details": "Common regional gateway via Istanbul; check current advisories.",
            },
            {
                "summary": "BEY → DAM, overland / short hop",
                "price_usd": 60,
                "details": "Beirut is a frequent overland entry; border rules vary.",
            },
            {
                "summary": "Local transit: taxis + Old City walking",
                "price_usd": 15,
                "details": "Old City is walkable; service taxis for longer hops.",
            },
        ],
        "pois": [
            {
                "name": "Umayyad Mosque",
                "category": "landmark",
                "lat": 33.5116,
                "lng": 36.3067,
                "estimated_duration_min": 90,
                "notes": "One of Islam's great early mosques; dress modestly.",
            },
            {
                "name": "Old City Souq al-Hamidiyah",
                "category": "neighborhood",
                "lat": 33.5110,
                "lng": 36.3045,
                "estimated_duration_min": 90,
                "notes": "Covered bazaar leading toward the Umayyad Mosque.",
            },
            {
                "name": "National Museum of Damascus",
                "category": "museum",
                "lat": 33.5128,
                "lng": 36.2900,
                "estimated_duration_min": 120,
                "notes": "Syrian antiquities from Ebla to Palmyra.",
            },
            {
                "name": "Abu Shaker",
                "category": "restaurant",
                "lat": 33.5155,
                "lng": 36.2950,
                "estimated_duration_min": 60,
                "notes": "Beloved local spot for mezze and grilled meats.",
            },
            {
                "name": "Bakdash Ice Cream",
                "category": "restaurant",
                "lat": 33.5112,
                "lng": 36.3055,
                "estimated_duration_min": 20,
                "notes": "Famous booza (pounded ice cream) in Souq al-Hamidiyah.",
            },
        ],
    },
    {
        "key": "los_angeles",
        "display_name": "Los Angeles",
        "country": "United States",
        "center": (34.0522, -118.2437),
        "aliases": [
            "los angeles",
            "los angeles ca",
            "losangeles",
            "la",
            "l.a.",
            "la california",
        ],
        "hotels": [
            {
                "name": "Freehand Los Angeles",
                "area": "Downtown",
                "nightly_rate_usd": 140,
                "lat": 34.0465,
                "lng": -118.2560,
                "notes": "Mid-range DTLA; good for Metro / walkable core.",
            },
            {
                "name": "HI Los Angeles Santa Monica Hostel",
                "area": "Santa Monica",
                "nightly_rate_usd": 75,
                "lat": 34.0125,
                "lng": -118.4950,
                "notes": "Budget near the pier and beach bike path.",
            },
            {
                "name": "Hotel Bel-Air",
                "area": "Bel Air",
                "nightly_rate_usd": 900,
                "lat": 34.0865,
                "lng": -118.4465,
                "notes": "Garden luxury; car recommended.",
            },
        ],
        "flights": [
            {
                "summary": "JFK → LAX, direct, ~6h",
                "price_usd": 320,
                "details": "LAX FlyAway bus to Union Station; rideshare common.",
            },
            {
                "summary": "LHR → LAX, direct, ~11h",
                "price_usd": 750,
                "details": "BA / AA / Virgin; long-haul jet lag planning advised.",
            },
            {
                "summary": "Local transit: Metro + rideshare",
                "price_usd": 50,
                "details": "Metro Rail useful for DTLA/Hollywood/Santa Monica; car still common.",
            },
        ],
        "pois": [
            {
                "name": "Griffith Observatory",
                "category": "landmark",
                "lat": 34.1184,
                "lng": -118.3004,
                "estimated_duration_min": 120,
                "notes": "Hollywood Sign views; free admission to building.",
            },
            {
                "name": "The Getty Center",
                "category": "museum",
                "lat": 34.0780,
                "lng": -118.4741,
                "estimated_duration_min": 180,
                "notes": "Free entry; parking fee; strong architecture + gardens.",
            },
            {
                "name": "Santa Monica Pier & Beach",
                "category": "neighborhood",
                "lat": 34.0100,
                "lng": -118.4965,
                "estimated_duration_min": 120,
                "notes": "Bike path toward Venice Boardwalk.",
            },
            {
                "name": "Grand Central Market",
                "category": "restaurant",
                "lat": 34.0507,
                "lng": -118.2487,
                "estimated_duration_min": 60,
                "notes": "DTLA food hall — tacos, coffee, produce.",
            },
            {
                "name": "Guelaguetza",
                "category": "restaurant",
                "lat": 34.0545,
                "lng": -118.2910,
                "estimated_duration_min": 75,
                "notes": "Oaxacan institution in Koreatown.",
            },
        ],
    },
]


def _alias_index() -> dict[str, CityFixture]:
    index: dict[str, CityFixture] = {}
    for city in _CITIES:
        for alias in city["aliases"]:
            index[alias.strip().lower()] = city
        index[city["key"]] = city
        index[city["display_name"].lower()] = city
    return index


_ALIAS_INDEX = _alias_index()


def normalize_destination(text: str | None) -> str:
    """Lowercase / strip a free-text destination for fixture lookup."""
    return (text or "").strip().lower()


def lookup_city(destination: str | None) -> CityFixture | None:
    """Resolve a destination string to a curated city fixture, or None."""
    raw = normalize_destination(destination)
    if not raw:
        return None
    if raw in _ALIAS_INDEX:
        return _ALIAS_INDEX[raw]
    # Try the first comma-separated token ("Paris, France").
    head = raw.split(",")[0].strip()
    if head in _ALIAS_INDEX:
        return _ALIAS_INDEX[head]
    # Word-boundary scan only (never bare substring — "la" must not match "Atlantis").
    return city_from_free_text(raw)


def list_mock_city_keys() -> list[str]:
    return [c["key"] for c in _CITIES]


def city_from_free_text(text: str) -> CityFixture | None:
    """Best-effort city detection inside a longer query ("restaurants in Paris")."""
    lowered = (text or "").lower()
    if not lowered:
        return None
    for alias in sorted(_ALIAS_INDEX.keys(), key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return _ALIAS_INDEX[alias]
    return None
