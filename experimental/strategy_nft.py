"""Strategy NFT — local-only ERC-721-style metadata for a strategy.

Hashes ``strategy code + params + git ref`` into a deterministic token id and
stores ERC-721-shaped metadata in a local registry (JSON file). No chain
integration: the registry is a flat file the user owns.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _sha256(*chunks: bytes) -> str:
    h = hashlib.sha256()
    for c in chunks:
        h.update(c)
    return h.hexdigest()


@dataclass
class StrategyNFT:
    """Mint and look up local NFT-style metadata for a strategy.

    Parameters
    ----------
    registry_path : Path
        Where the JSON registry lives. Created on first ``mint``.
    """

    registry_path: Path

    def __post_init__(self) -> None:
        self.registry_path = Path(self.registry_path)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self.registry_path.write_text("{}", encoding="utf-8")

    def _load(self) -> dict:
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def _save(self, data: dict) -> None:
        self.registry_path.write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )

    def mint(
        self,
        name: str,
        strategy_code: str,
        params: dict,
        git_ref: str = "HEAD",
        description: Optional[str] = None,
    ) -> dict:
        """Hash inputs into a token id and store ERC-721-shaped metadata."""
        param_blob = json.dumps(params, sort_keys=True).encode()
        token_id = _sha256(
            strategy_code.encode(), param_blob, git_ref.encode(), name.encode()
        )
        metadata = {
            "token_id": token_id,
            "name": name,
            "description": description or f"Strategy NFT for {name}",
            "attributes": [
                {"trait_type": "git_ref", "value": git_ref},
                {"trait_type": "param_count", "value": len(params)},
                {"trait_type": "code_sha256", "value": _sha256(strategy_code.encode())},
            ],
            "params": params,
        }
        registry = self._load()
        if token_id in registry:
            # Idempotent: re-minting the same inputs returns the existing record.
            return registry[token_id]
        registry[token_id] = metadata
        self._save(registry)
        return metadata

    def get(self, token_id: str) -> Optional[dict]:
        return self._load().get(token_id)

    def list_tokens(self) -> list[dict]:
        return list(self._load().values())
