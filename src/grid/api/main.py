"""FastAPI application shell.

Real endpoints land in Phase 3 (docs/context/roadmap.md); only a liveness probe and
the auto-generated /docs Swagger page exist until then. No dashboard UI is built in
this repo — that is Claude Design's scope via docs/handoff/.
"""

from __future__ import annotations

from fastapi import FastAPI

from grid import __version__

app = FastAPI(
    title="GRID API",
    version=__version__,
    description=(
        "GP Registry & Intelligence Database — engagement queues for the PMCare PNM team. "
        "PMCare is a neutral TPA; this service provides discovery data only."
    ),
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "version": __version__}
