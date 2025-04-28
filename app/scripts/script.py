from abc import ABC, abstractmethod
from pydantic import BaseModel


class Script(ABC):

    class Result(ABC, BaseModel):
        pass

    @abstractmethod
    def run(self) -> Result:
        pass
