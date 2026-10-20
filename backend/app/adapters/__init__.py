"""Simulated device and service adapters.

The adapter boundary is the integration point: a real implementation replaces a
class here without changing the tools, rules, or audit code.
"""

from app.adapters.lights import LightAdapter
from app.adapters.timers import TimerAdapter

__all__ = ["LightAdapter", "TimerAdapter"]
