from abc import ABC, abstractmethod
from typing import Any, Type

from pydantic import BaseModel


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str) -> str: ...

    @abstractmethod
    async def generate_structured(self, prompt: str, schema: Type[BaseModel]) -> Any: ...
