from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import RawPost


class Collector(ABC):
    name: str = "collector"

    def __init__(self) -> None:
        self.errors: list[str] = []

    @abstractmethod
    def collect(self) -> list[RawPost]:
        """Return recent posts. Must not log in, bypass protections, or follow post links."""
