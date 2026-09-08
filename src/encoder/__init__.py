"""Trust-aware structured state encoder — Defense Layer 2 (blueprint §7/§10).

Public API re-exported here so callers write `from src.encoder import
StateEncoder` rather than reaching into `state_encoder` directly.
"""

from src.encoder.state_encoder import (
    ClusterSnapshot,
    EncodedState,
    StateEncoder,
    SystemContext,
    TenantNarrative,
)

__all__ = [
    "ClusterSnapshot",
    "EncodedState",
    "StateEncoder",
    "SystemContext",
    "TenantNarrative",
]