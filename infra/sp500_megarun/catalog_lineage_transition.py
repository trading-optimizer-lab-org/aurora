"""Protected lineage permissions shared by the controller and maintenance package."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field

from .catalog_request_contract import CatalogLaunchTicketV1, CatalogRunRequestV1, FrozenModel, Sha256


class CatalogLineageTransitionV1(FrozenModel):
    """Exact boundary approved in protected configuration, never request input.

    This permission does not terminalize a run or rewrite a signed predecessor.
    Both admission and the serialized writer must load it from protected code.
    """

    campaign_key: str = Field(min_length=1, max_length=128)
    previous_request_sha256: Sha256
    next_generation: int = Field(strict=True, ge=2)
    target_definition_sha256: Sha256
    target_prompt_sha256: Sha256

    def authorizes(self, previous: CatalogRunRequestV1, request: CatalogRunRequestV1 | CatalogLaunchTicketV1) -> bool:
        return (
            self.campaign_key == previous.campaign_key == request.campaign_key
            and self.previous_request_sha256 == previous.request_sha256
            and request.previous_terminal_request_sha256 == previous.request_sha256
            and self.next_generation == previous.launch_generation + 1 == request.launch_generation
            and self.target_definition_sha256 == request.campaign_definition_sha256
            and self.target_prompt_sha256 == request.prompt_sha256
        )


def load_lineage_transition(repo_root: Path, request: CatalogRunRequestV1 | CatalogLaunchTicketV1) -> CatalogLineageTransitionV1 | None:
    """Read a bounded, fixed protected file; absence never grants permission."""
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result

    try:
        root = repo_root.resolve(strict=True)
        path = root / "config/catalog_lineage_transitions_v1.json"
        if repo_root.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("unsafe path")
        try:
            with path.open("rb") as stream:
                raw = stream.read(65537)
        except FileNotFoundError:
            return None
        if len(raw) > 65536:
            raise ValueError("oversized configuration")
        payload = json.loads(raw, object_pairs_hook=unique_object)
        if (not isinstance(payload, dict) or set(payload) != {"schema_version", "transitions"}
            or payload["schema_version"] != "1" or not isinstance(payload["transitions"], list)
            or len(payload["transitions"]) > 128):
            raise ValueError("invalid configuration")
        rows = tuple(CatalogLineageTransitionV1.model_validate(row) for row in payload["transitions"])
        keys = [(row.campaign_key, row.next_generation) for row in rows]
        if len(keys) != len(set(keys)):
            raise ValueError("ambiguous boundary")
        return next((row for row in rows if (row.campaign_key, row.next_generation) ==
                     (request.campaign_key, request.launch_generation)), None)
    except (ValueError, TypeError, OSError) as exc:
        raise ValueError("CATALOG_LINEAGE_CONFIG_INVALID") from exc
