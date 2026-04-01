"""Abstract project storage interface."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ProjectStore(ABC):
    """Abstract interface for project persistence.

    Implementations can use SQLite, Postgres, or any other backend.
    """

    @abstractmethod
    def create_project(self, project_id: str, data: Dict[str, Any]) -> None:
        ...

    @abstractmethod
    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        ...

    @abstractmethod
    def update_project(self, project_id: str, data: Dict[str, Any]) -> None:
        ...

    @abstractmethod
    def list_projects(self) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def delete_project(self, project_id: str) -> bool:
        ...
