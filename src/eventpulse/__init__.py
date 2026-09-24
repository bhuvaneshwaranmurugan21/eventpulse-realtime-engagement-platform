"""EventPulse streaming correctness kernel."""

from .model import EngagementEvent
from .processor import StreamProcessor

__all__ = ["EngagementEvent", "StreamProcessor"]

