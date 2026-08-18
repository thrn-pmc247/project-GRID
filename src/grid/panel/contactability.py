"""Whether a provider can be phoned — a boolean derived from personal data.

This module is deliberately separate from `grid.panel.suppression`, which promises in
its docstring never to select a personal-data column. That promise is what lets Queue B
back a shareable view, and it should not be quietly broken to save a file.

What crosses the boundary here is a **boolean, never a number**. "This clinic has a
usable telephone number on record" is business information: it says nothing about any
individual, it cannot be dialled, and it is exactly what the priority bands need in
order to sort unreachable rows last. The number itself stays in `pii.provider_contact`.

Mobile numbers are excluded by default. Under `docs/context/compliance-pdpa.md` a sole
proprietor's mobile is personal data in a way a clinic landline is not, and PNM's
outreach is specified against the **published business line**
(`docs/context/compliance-outreach.md`). Counting a personal mobile as "contactable"
would quietly promote rows we may not be permitted to ring.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

import structlog
from sqlalchemy import Engine, select

from grid.db.models import PiiProviderContact
from grid.normalise.phones import LineType, PhoneQuality, normalise_phone

log = structlog.get_logger(__name__)

BUSINESS_LINE_TYPES: Final[frozenset[LineType]] = frozenset(
    {LineType.FIXED_LINE, LineType.OTHER, LineType.UNKNOWN}
)
"""Line types treated as a business line.

`OTHER` covers toll-free ranges such as 1300, which are business hunting lines despite
their E.164 form resembling a mobile number — see `grid.normalise.phones`.
"""


@dataclass(frozen=True, slots=True)
class ContactabilitySummary:
    """Counts only. Deliberately holds no number and no provider identity."""

    considered: int
    contactable: int
    mobile_only: int
    invalid_or_missing: int


def contactability(
    engine: Engine,
    *,
    include_mobiles: bool = False,
) -> tuple[Mapping[str, bool], ContactabilitySummary]:
    """Map provider code to "has a usable business line", plus the counts.

    Args:
        engine: Engine with `pii.provider_contact` populated.
        include_mobiles: Count a mobile number as contactable. Defaults False — see the
            module docstring. Setting it True is a PDPA decision, not a tuning knob.

    Returns:
        A `{provider_code: bool}` mapping suitable for `grid.score.priority.rank`, and a
        counts-only summary safe to log.
    """
    stmt = select(PiiProviderContact.provider_code, PiiProviderContact.general_phone_no)

    reachable: dict[str, bool] = {}
    contactable = mobile_only = invalid = 0

    with engine.connect() as conn:
        for code, raw in conn.execute(stmt):
            parts = normalise_phone(raw)
            if parts.quality is not PhoneQuality.VALID:
                reachable[str(code)] = False
                invalid += 1
                continue
            if parts.is_mobile and not include_mobiles:
                reachable[str(code)] = False
                mobile_only += 1
                continue
            reachable[str(code)] = parts.line_type in BUSINESS_LINE_TYPES or parts.is_mobile
            if reachable[str(code)]:
                contactable += 1
            else:
                invalid += 1

    summary = ContactabilitySummary(
        considered=len(reachable),
        contactable=contactable,
        mobile_only=mobile_only,
        invalid_or_missing=invalid,
    )
    # Counts only — never a number, never a provider code (conventions.md: never log PII).
    log.info(
        "contactability.assessed",
        considered=summary.considered,
        contactable=summary.contactable,
        mobile_only=summary.mobile_only,
        invalid_or_missing=summary.invalid_or_missing,
        include_mobiles=include_mobiles,
    )
    return reachable, summary
