"""Enrichment: geocoding and recency-signal fusion.

Google Places guardrail: persist place_id ONLY — no other Places content may have a
persistence path (docs/context/compliance-scraping.md). recency.py fuses signals
into opened_confidence. Phases 1 and 2.
"""
