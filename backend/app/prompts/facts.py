"""Closed Northstar One fact sheet — the ONLY facts the agent may state.

Every other project detail (possession, amenities, RERA, discounts, unit
availability, carpet/built-up area, floor plans, loan rates) is unknown and
must follow the unknown-question fallback ladder in the system prompt.
"""

from __future__ import annotations

COMPANY_NAME = "Northstar Homes"
PROJECT_NAME = "Northstar One"
LOCATION = "Sector 79, Gurugram"

CONFIGURATIONS: tuple[str, ...] = ("2 BHK", "3 BHK")

PRICE_2BHK_CRORE = 1.35
PRICE_3BHK_CRORE = 1.75
PRICE_2BHK_DISPLAY = "₹1.35 crore onwards"
PRICE_3BHK_DISPLAY = "₹1.75 crore onwards"
PRICE_PHRASING = 'Always quote prices with "onwards" or "starting from". Never as a fixed/final price.'

SITE_VISITS_NOTE = (
    "Site visits are available. Exact dates and times come from the booking "
    "system only — never invent a slot, confirmation ID, or availability."
)

# Substrings a reply may use when mentioning price. Stage 04 post-check uses these.
CANONICAL_PRICE_SUBSTRINGS: tuple[str, ...] = ("1.35", "1.75")

UNKNOWN_TOPICS: tuple[str, ...] = (
    "possession or handover dates",
    "discounts, offers, or schemes",
    "unit availability or inventory",
    "amenities, specifications, or floor plans",
    "carpet area, built-up area, or super area",
    "RERA number or registration status",
    "loan approval, interest rates, or EMI figures",
    "tax, stamp duty, or legal advice",
    "competitor quality, pricing, or delivery",
    "builder promises such as guaranteed appreciation",
)

FACTS_HEADER = "## FACTS"


def render_facts_block() -> str:
    """Human-readable closed fact sheet injected into the system prompt."""
    unknown = "; ".join(UNKNOWN_TOPICS)
    configs = " and ".join(CONFIGURATIONS)
    return f"""{FACTS_HEADER}
This is a CLOSED fact sheet. You may state ONLY what is listed here. Everything else is unknown.

- Company: {COMPANY_NAME}
- Project: {PROJECT_NAME}
- Location: {LOCATION}
- Configurations: {configs}
- 2 BHK price: {PRICE_2BHK_DISPLAY}
- 3 BHK price: {PRICE_3BHK_DISPLAY}
- {PRICE_PHRASING}
- {SITE_VISITS_NOTE}

Unknown (do not guess): {unknown}."""
