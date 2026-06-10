"""Provider catalog interfaces for deterministic placement decisions."""

from abc import ABC, abstractmethod
from typing import Optional

from archway_diagram_compiler.models import IconRef, ServiceInfo, ServiceNode


class ProviderCatalog(ABC):
    provider_id: str

    @abstractmethod
    def canonicalize_service(self, service: str) -> str:
        """Return the provider's canonical service identifier."""

    @abstractmethod
    def get_service_info(self, service: str) -> ServiceInfo:
        """Return catalog metadata for a canonical or aliased service name."""

    @abstractmethod
    def get_icon(self, service: str) -> IconRef:
        """Return the preferred icon reference for a service."""

    @abstractmethod
    def get_default_category(self, service: str) -> str:
        """Return the default semantic category for a service."""

    @abstractmethod
    def get_placement_scope(self, service: str, node: ServiceNode) -> str:
        """Return the placement scope for a service in the context of a node."""

    @abstractmethod
    def get_endpoint_type(self, service: str) -> Optional[str]:
        """Return the private endpoint type for a managed service, if supported."""
