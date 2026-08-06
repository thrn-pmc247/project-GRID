"""Snapshot store and differ.

snapshots.py: immutable timestamped snapshots (data/raw/<source>/<date>/, checksummed
in the snapshot table). differ.py: separates genuinely-new records from
newly-listed-but-pre-existing ones (Queue A vs Queue B rule —
docs/context/entity-resolution.md). Phase 1.
"""
