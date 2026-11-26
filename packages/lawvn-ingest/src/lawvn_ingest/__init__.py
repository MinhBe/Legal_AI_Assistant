"""lawvn-ingest: pluggable media ingest for Legal Agentic (and Pi). See docs/design/ingest-contract.md."""

from .core import CONSENT, Adapter, Item, Store, adapters, get_adapter, ingest, stem_for

__all__ = ["CONSENT", "Adapter", "Item", "Store", "adapters", "get_adapter", "ingest", "stem_for"]
