"""Trust-aware structured state encoder — Defense Layer 2 (blueprint §7/§10).

Public API re-exported here so callers write `from src.encoder import
TrustAwareStateEncoder` rather than reaching into `state_encoder` directly.
"""

from src.encoder.state_encoder import EncodedState, TrustAwareStateEncoder

__all__ = [
    "EncodedState",
    "TrustAwareStateEncoder",
]