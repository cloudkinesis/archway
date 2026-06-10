"""Provider catalog registry."""

from typing import Dict

from archway_diagram_compiler.aws_provider import AWS_PROVIDER
from archway_diagram_compiler.provider_catalog import ProviderCatalog


PROVIDERS: Dict[str, ProviderCatalog] = {AWS_PROVIDER.provider_id: AWS_PROVIDER}


def get_provider_catalog(provider_id: str) -> ProviderCatalog:
    try:
        return PROVIDERS[provider_id]
    except KeyError as exc:
        raise KeyError(f"Unsupported provider: {provider_id}") from exc
