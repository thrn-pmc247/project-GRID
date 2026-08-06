"""Seed obviously-synthetic clinic records for local development.

Writes JSON to data/interim/synthetic_clinics.json. Every value is fabricated and
recognisably fake — no real clinic names, addresses, registration numbers or phone
numbers (see CLAUDE.md guardrail 5). Phase 1 extends this to load the records into
the database once migrations exist.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "interim" / "synthetic_clinics.json"

SYNTHETIC_CLINICS: list[dict[str, object]] = [
    {
        "name": "Klinik Contoh Satu",
        "address": "No. 1, Jalan Contoh 1/1, Taman Contoh",
        "postcode": "40000",
        "state": "Selangor",
        "phone_e164": "+60300000001",  # fake fixed line, not a mobile
        "scope": "gp",
        "source": "synthetic",
    },
    {
        "name": "Poliklinik Contoh Dua & Surgery",
        "address": "Lot 2, Tingkat Bawah, Blok B, Jalan Contoh 2",
        "postcode": "88000",
        "state": "Sabah",
        "phone_e164": "+60800000002",
        "scope": "gp",
        "source": "synthetic",
    },
    {
        "name": "Klinik Pergigian Contoh",  # dental — must be excluded by gp_filter
        "address": "No. 3, Persiaran Contoh, Taman Contoh Jaya",
        "postcode": "93000",
        "state": "Sarawak",
        "phone_e164": "+60800000003",
        "scope": "excluded",
        "source": "synthetic",
    },
]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(SYNTHETIC_CLINICS, indent=2), encoding="utf-8")
    print(f"wrote {len(SYNTHETIC_CLINICS)} synthetic clinics -> {OUT}")


if __name__ == "__main__":
    main()
