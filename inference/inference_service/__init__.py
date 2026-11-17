"""Internal inference service (POST /internal/infer, POST /internal/models/load from Phase D2).

Stateless, no database access. It may not import the ``api`` package (dependency direction
frontend -> api -> inference -> ml_research), so it keeps its own small copy of the error
envelope, request-ID middleware and JSON logging (ADR-0001).
"""

__version__ = "0.1.0"
