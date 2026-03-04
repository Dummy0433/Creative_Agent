"""Abstract base classes for generation providers."""

from abc import ABC, abstractmethod


class ImageProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> bytes:
        ...


class TextProvider(ABC):
    @abstractmethod
    def generate(self, model: str, system_prompt: str, user_prompt: str) -> dict:
        ...
