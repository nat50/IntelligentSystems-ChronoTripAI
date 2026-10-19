"""Foursquare category -> candidate group, effort level and category priors.

Only five groups are kept as candidate places (spec II.4): sightseeing,
entertainment, food, nightlife and shopping. The effort level e_i (1..5) is a
lookup table by category (spec IV.1), not a learned model.
"""

from __future__ import annotations

import re

GROUPS = ("sightseeing", "entertainment", "food", "nightlife", "shopping")

# (pattern, group, effort, short display label). First match wins, order matters.
_RULES: list[tuple[str, str, int, str]] = [
    # nightlife
    (r"night ?club|disco|karaoke|lounge|hookah|speakeasy", "nightlife", 3, "Nightclub"),
    (r"night ?market", "shopping", 3, "Night market"),
    (r"\bbar\b|\bpub\b|brewery|beer|wine|cocktail|\bsake\b|nightlife", "nightlife", 1, "Bar"),
    # entertainment (heavier ones first)
    (r"theme park|amusement|water ?park", "entertainment", 5, "Theme park"),
    (r"\bzoo\b|aquarium", "entertainment", 4, "Zoo"),
    (r"stadium|arena|race ?track|go ?kart|bowling|climbing|skate|ice rink", "entertainment", 4, "Sports venue"),
    (r"movie|cinema|theater|theatre|concert|music venue|comedy|performing arts|opera", "entertainment", 1, "Theater"),
    (r"arcade|casino|pool hall|\bgames?\b|escape room", "entertainment", 2, "Arcade"),
    # sightseeing
    (r"museum|gallery|\barts?\b|exhibit|planetarium|science", "sightseeing", 2, "Museum"),
    (r"temple|pagoda|church|cathedral|mosque|shrine|spiritual|monastery", "sightseeing", 2, "Temple"),
    (r"historic|monument|landmark|palace|castle|memorial|\bfort\b|ruins|heritage", "sightseeing", 2, "Landmark"),
    (r"mountain|hiking|\btrail\b|volcano|waterfall|\bcave\b|national park", "sightseeing", 5, "Trail"),
    (r"beach|island|\blake\b|river|harbor|marina|\bpier\b|\bbay\b", "sightseeing", 3, "Waterfront"),
    (r"garden|\bpark\b|plaza|square|scenic|lookout|outdoors|bridge", "sightseeing", 3, "Park"),
    # shopping
    (r"market|bazaar|\bflea\b", "shopping", 3, "Market"),
    (r"\bmall\b|shopping|department store|outlet|boutique|clothing|bookstore|souvenir|\bgift", "shopping", 2, "Mall"),
    # food
    (r"caf[eé]|coffee|tea ?room|bubble tea|dessert|bakery|ice cream|juice|smoothie", "food", 1, "Café"),
    (r"vietnam|\bpho\b|noodle", "food", 1, "Vietnamese kitchen"),
    (r"street food|food truck|food court|hawker|snack", "food", 1, "Street food"),
    (
        r"restaurant|food|diner|bistro|steakhouse|bbq|grill|seafood|sushi|ramen|pizza|burger|buffet|eatery|kitchen",
        "food",
        1,
        "Restaurant",
    ),
]

# Venues that are never itinerary candidates, checked before the rules above
_EXCLUDE = re.compile(
    r"supermarket|grocery|convenience|pharmacy|drugstore|gas station|\bbank\b|office|\bhome\b|residential|"
    r"apartment|hotel|hostel|airport|\bbus\b|\btrain\b|metro|subway|school|university|college|hospital|"
    r"parking|government|factory|building|\broad\b|intersection|neighborhood|\bcity\b|\btown\b|trailer",
    re.I,
)
_COMPILED = [(re.compile(p, re.I), g, e, label) for p, g, e, label in _RULES]


def fix_encoding(name: str) -> str:
    """Repair UTF-8 text that was decoded as Latin-1 (e.g. 'CafÃ©' -> 'Café')."""
    if not isinstance(name, str):
        return ""
    if "Ã" in name or "Â" in name:
        try:
            return name.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return name
    return name


def classify(category: str) -> tuple[str | None, int, str]:
    """Return (group or None if not a candidate, effort 1..5, display label)."""
    cat = fix_encoding(category)
    if _EXCLUDE.search(cat):
        return None, 2, cat
    for rx, group, effort, label in _COMPILED:
        if rx.search(cat):
            return group, effort, label
    return None, 2, cat


# Category-level priors (minutes since midnight) used when a place has too few
# check-ins and as the M2 / M3 fallback.
GROUP_PRIORS: dict[str, dict[str, float]] = {
    "sightseeing": dict(open=7 * 60, close=18 * 60, golden=8 * 60, duration=75),
    "entertainment": dict(open=9 * 60, close=22 * 60, golden=15 * 60, duration=120),
    "food": dict(open=7 * 60, close=22 * 60, golden=12 * 60, duration=60),
    "nightlife": dict(open=17 * 60, close=26 * 60, golden=20 * 60, duration=90),
    "shopping": dict(open=9 * 60, close=22 * 60, golden=17 * 60, duration=60),
}
