"""Central, immutable policy object for the QuantForge research protocol.

P0.A goal: turn ``RESEARCH_PROTOCOL.md`` from documentation into enforced
code. Every module that previously hard-coded a tier date, a ceremony name,
or a validation gate now reads it from :class:`ProtocolPolicy`.

Design contract
---------------

* The policy is a frozen dataclass (``frozen=True``). Mutation raises
  :class:`dataclasses.FrozenInstanceError`. Use :func:`dataclasses.replace`
  to derive a new policy for tests.
* :func:`ProtocolPolicy.default` returns the current production policy with
  the constants in :mod:`aurora.core.data_tiers`,
  :mod:`quantforge.validation.pipeline`, :mod:`quantforge.ga.runner`, and
  :mod:`aurora.core.costs` reproduced as data.
* :func:`ProtocolPolicy.load` reads ``quantforge/config/protocol_policy.yaml``
  if it exists and otherwise falls back to :func:`default`.
* :attr:`ProtocolPolicy.policy_hash` is a deterministic ``sha256`` digest of
  the canonical JSON dump (``sort_keys=True``, no extra whitespace). The
  same policy on any Python version produces the same digest.
* The hash field on a YAML file is treated as a *declared* hash. Verifying a
  policy means recomputing the hash from the data and comparing it to the
  declaration -- a mismatch implies the YAML was tampered with.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Dict, List, Optional


PROTOCOL_VERSION = "1.4.0"


# --------------------------------------------------------------------------
# Inner config dataclasses
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TierConfig:
    """Date window and access policy for one protocol tier."""

    start: str
    end: Optional[str]  # None = unbounded (FORWARD)
    purpose: str
    requires_ceremony: Optional[str] = None  # ceremony env_flag name


@dataclass(frozen=True)
class CeremonyConfig:
    """Named OOS-unlock ceremony.

    Attributes:
        env_flag: The ``OOSGuard.phase`` string this ceremony presents.
        requires_oos_guard: ``True`` iff calling code must be inside an
            ``OOSGuard`` whose phase matches ``env_flag``.
        requires_signed_authorization: ``True`` iff a co-signed lockbox
            request file is mandatory (the lockbox ceremony, doc section
            "Lockbox ceremony for OOS_LOCKED").
        purpose_pattern: Suggested provenance label for reads under this
            ceremony.
    """

    env_flag: str
    requires_oos_guard: bool = True
    requires_signed_authorization: bool = False
    purpose_pattern: str = ""


@dataclass(frozen=True)
class RiskLimits:
    """Risk caps applied by deployment wrappers."""

    max_leverage: float = 1.0
    max_drawdown_promotion_threshold: float = 0.30
    max_position_concentration: float = 1.0
    max_correlation_to_benchmark: float = 0.95


@dataclass(frozen=True)
class CostModelConfig:
    """Default cost-floor used by every research backtest."""

    commission_bps: float = 0.5
    spread_bps: float = 1.0
    slippage_bps: float = 2.0
    borrow_rate_annual: float = 0.01
    slippage_model_id: str = "constant_bps"
    market_impact_id: str = "linear_sqrt_volume"


@dataclass(frozen=True)
class StressConfig:
    """Required stress scenario for promotion."""

    name: str
    start: str
    end: str
    description: str = ""


@dataclass(frozen=True)
class DCAConfig:
    """Defensive Capital Allocation config (regime overlay)."""

    sma_long: int = 200
    sma_short: int = 50
    vol_regime_threshold: float = 0.20


@dataclass(frozen=True)
class ObjectiveConfig:
    """One IS objective or one OOS validation threshold."""

    name: str
    direction: str  # "max" or "min"
    threshold: Optional[float] = None  # None for IS objectives, value for OOS
    description: str = ""


@dataclass(frozen=True)
class GAConfigPolicy:
    """GA defaults at the protocol level.

    These are the *floor* values; per-call overrides via
    ``quantforge.ga.runner.GAConfig`` are still allowed but should not
    drop below these.
    """

    population: int = 200
    generations: int = 50
    crossover_prob: float = 0.7
    mutation_prob: float = 0.2
    tournament_size: int = 3
    seed: int = 42
    sampler: str = "nsga2"
    seed_population_policy: str = "random"
    n_workers: int = 1
    backend: str = "sequential"


# --------------------------------------------------------------------------
# Top-level policy
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ProtocolPolicy:
    """Single source of truth for the QuantForge research protocol.

    See module docstring for the immutability contract.
    """

    tiers: Dict[str, TierConfig]
    mandatory_gates: List[str]
    oos_ceremonies: Dict[str, CeremonyConfig]
    risk_limits: RiskLimits
    cost_model: CostModelConfig
    stress_scenarios: List[StressConfig]
    dca_config: DCAConfig
    objectives: List[ObjectiveConfig]
    ga_config: GAConfigPolicy
    version: str = PROTOCOL_VERSION
    policy_hash: str = ""  # filled by ``__post_init__``-equivalent factory

    # ----- factories -------------------------------------------------------

    @classmethod
    def default(cls) -> "ProtocolPolicy":
        """Return the current production policy.

        The values mirror the existing module-level constants in
        :mod:`aurora.core.data_tiers`,
        :mod:`quantforge.validation.pipeline`, :mod:`quantforge.ga.runner`
        and :mod:`aurora.core.costs` as of v3.0.
        """
        tiers = {
            "IS_TRAIN": TierConfig(
                start="1995-01-01",
                end="2010-12-31",
                purpose="Model fitting",
                requires_ceremony=None,
            ),
            "IS_VALID": TierConfig(
                start="2011-01-01",
                end="2012-12-31",
                purpose="In-sample walk-forward holdout",
                requires_ceremony=None,
            ),
            "OOS_DEV": TierConfig(
                start="2013-01-01",
                end="2020-12-31",
                purpose="Post-GA validation, may be re-touched after a "
                        "research-cycle reset",
                requires_ceremony=None,
            ),
            "OOS_LOCKED": TierConfig(
                start="2021-01-01",
                end="2024-12-31",
                purpose="Frozen, single-look only",
                requires_ceremony="explicit_unlock_oos_locked",
            ),
            "FORWARD": TierConfig(
                start="2025-01-01",
                end=None,
                purpose="Paper / live trading",
                requires_ceremony="explicit_unlock_forward",
            ),
        }
        mandatory_gates = [
            "walk_forward",
            "monte_carlo_bootstrap",
            "monte_carlo_trade_reorder",
            "spp",
            "lookahead_check",
            "deflated_sharpe",
            "noise_injection",
            "gap_simulation",
            # P1.B: auditor gate (multi-agent reviewers). Additive --
            # promotion requires the audit report to carry no HARD_FAIL.
            "auditor_gate",
        ]
        ceremonies = {
            "explicit_unlock_snapshot": CeremonyConfig(
                env_flag="explicit_unlock_snapshot",
                requires_oos_guard=True,
                requires_signed_authorization=False,
                purpose_pattern="snapshot_load",
            ),
            "explicit_unlock_oos_locked": CeremonyConfig(
                env_flag="explicit_unlock_oos_locked",
                requires_oos_guard=True,
                requires_signed_authorization=True,
                purpose_pattern="oos_locked_read",
            ),
            "explicit_unlock_forward": CeremonyConfig(
                env_flag="explicit_unlock_forward",
                requires_oos_guard=True,
                requires_signed_authorization=False,
                purpose_pattern="forward_read",
            ),
            "explicit_unlock_full_tier": CeremonyConfig(
                env_flag="explicit_unlock_full_tier",
                requires_oos_guard=True,
                requires_signed_authorization=True,
                purpose_pattern="cli_analysis_full_tier",
            ),
        }
        risk_limits = RiskLimits(
            max_leverage=1.0,
            max_drawdown_promotion_threshold=0.30,
            max_position_concentration=1.0,
            max_correlation_to_benchmark=0.95,
        )
        cost_model = CostModelConfig(
            commission_bps=0.5,
            spread_bps=1.0,
            slippage_bps=2.0,
            borrow_rate_annual=0.01,
            slippage_model_id="constant_bps",
            market_impact_id="linear_sqrt_volume",
        )
        stress_scenarios = [
            StressConfig(name="2008_GFC", start="2007-10-01",
                         end="2009-06-30",
                         description="Global Financial Crisis"),
            StressConfig(name="COVID_2020", start="2020-02-15",
                         end="2020-04-30",
                         description="COVID-19 pandemic crash"),
            StressConfig(name="DOTCOM_2000", start="2000-03-01",
                         end="2002-10-31",
                         description="Dot-com bust"),
            StressConfig(name="VOL_2018Q4", start="2018-10-01",
                         end="2018-12-31",
                         description="Q4 2018 volatility blow-up"),
        ]
        dca = DCAConfig(sma_long=200, sma_short=50,
                        vol_regime_threshold=0.20)
        objectives = [
            ObjectiveConfig(name="calmar_is", direction="max",
                            threshold=None,
                            description="Calmar ratio on IS"),
            ObjectiveConfig(name="sharpe_is", direction="max",
                            threshold=None,
                            description="Sharpe ratio on IS"),
            ObjectiveConfig(name="robustness_wf", direction="max",
                            threshold=None,
                            description="Walk-forward stability "
                                        "(neg-stddev of per-fold Calmar)"),
            ObjectiveConfig(name="mdd_penalty_is", direction="min",
                            threshold=None,
                            description="IS max-drawdown penalty"),
            ObjectiveConfig(name="dsr_oos", direction="max",
                            threshold=0.95,
                            description="Deflated Sharpe gate on OOS"),
            ObjectiveConfig(name="wf_pass", direction="max",
                            threshold=3.0,
                            description="Min walk-forward folds passed"),
            ObjectiveConfig(name="spp_cv", direction="min",
                            threshold=0.30,
                            description="Max SPP Calmar CV"),
        ]
        ga_config = GAConfigPolicy(
            population=200,
            generations=50,
            crossover_prob=0.7,
            mutation_prob=0.2,
            tournament_size=3,
            seed=42,
            sampler="nsga2",
            seed_population_policy="random",
            n_workers=1,
            backend="sequential",
        )

        # Build w/ empty hash, then compute and return a finalized instance.
        scaffold = cls(
            tiers=tiers,
            mandatory_gates=mandatory_gates,
            oos_ceremonies=ceremonies,
            risk_limits=risk_limits,
            cost_model=cost_model,
            stress_scenarios=stress_scenarios,
            dca_config=dca,
            objectives=objectives,
            ga_config=ga_config,
            version=PROTOCOL_VERSION,
            policy_hash="",
        )
        return scaffold._with_hash()

    # ----- hashing ---------------------------------------------------------

    def _canonical_dict(self) -> Dict[str, Any]:
        """Return a deterministic dict representation excluding ``policy_hash``.

        Used for hashing; the hash field itself never participates in its
        own digest.
        """
        d = self.to_dict()
        d.pop("policy_hash", None)
        return d

    def compute_hash(self) -> str:
        """Recompute the deterministic ``sha256`` digest."""
        payload = json.dumps(self._canonical_dict(),
                             sort_keys=True,
                             separators=(",", ":"),
                             ensure_ascii=True,
                             default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _with_hash(self) -> "ProtocolPolicy":
        """Return a copy with ``policy_hash`` filled in deterministically."""
        return replace(self, policy_hash=self.compute_hash())

    def verify_hash(self, declared_hash: Optional[str] = None) -> bool:
        """True iff the recomputed hash matches the declared / stored one."""
        target = declared_hash if declared_hash is not None else self.policy_hash
        return self.compute_hash() == target

    # ----- (de)serialization -----------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON / YAML-friendly dict."""
        # ``asdict`` already recurses through nested dataclasses. We just
        # need to coerce dict[str, dataclass] inner values, which asdict
        # already handles (it produces dict[str, dict]).
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProtocolPolicy":
        """Inverse of :meth:`to_dict`. Recomputes ``policy_hash``."""
        tiers = {k: TierConfig(**v) for k, v in (data.get("tiers") or {}).items()}
        ceremonies = {
            k: CeremonyConfig(**v)
            for k, v in (data.get("oos_ceremonies") or {}).items()
        }
        risk_limits = RiskLimits(**(data.get("risk_limits") or {}))
        cost_model = CostModelConfig(**(data.get("cost_model") or {}))
        stress_scenarios = [
            StressConfig(**s) for s in (data.get("stress_scenarios") or [])
        ]
        dca = DCAConfig(**(data.get("dca_config") or {}))
        objectives = [
            ObjectiveConfig(**o) for o in (data.get("objectives") or [])
        ]
        ga_config = GAConfigPolicy(**(data.get("ga_config") or {}))

        scaffold = cls(
            tiers=tiers,
            mandatory_gates=list(data.get("mandatory_gates") or []),
            oos_ceremonies=ceremonies,
            risk_limits=risk_limits,
            cost_model=cost_model,
            stress_scenarios=stress_scenarios,
            dca_config=dca,
            objectives=objectives,
            ga_config=ga_config,
            version=str(data.get("version") or PROTOCOL_VERSION),
            policy_hash="",
        )
        return scaffold._with_hash()

    @classmethod
    def from_json(cls, path: str) -> "ProtocolPolicy":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    @classmethod
    def from_yaml(cls, path: str) -> "ProtocolPolicy":
        import yaml  # PyYAML is already a dep
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    def to_yaml(self, path: Optional[str] = None) -> str:
        """Serialize as YAML. Returns the YAML string and optionally writes."""
        import yaml
        text = yaml.safe_dump(
            self.to_dict(), sort_keys=True, default_flow_style=False,
            allow_unicode=True,
        )
        if path is not None:
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".",
                        exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        return text

    # ----- loader ----------------------------------------------------------

    @staticmethod
    def default_yaml_path() -> str:
        """Canonical on-disk location for the protocol policy YAML."""
        # /quantforge/core/protocol_policy.py -> /quantforge/config/protocol_policy.yaml
        here = Path(__file__).resolve().parent
        return str(here.parent / "config" / "protocol_policy.yaml")

    @classmethod
    def load(cls, path: Optional[str] = None) -> "ProtocolPolicy":
        """Load from YAML if present, otherwise return :meth:`default`.

        ``path`` defaults to :func:`default_yaml_path`. The loader does
        NOT raise if the file is missing -- a missing YAML simply means
        "use the in-code default" -- but it DOES raise on a malformed
        file so silent corruption never propagates.
        """
        target = path or cls.default_yaml_path()
        if not os.path.exists(target):
            return cls.default()
        return cls.from_yaml(target)


# --------------------------------------------------------------------------
# Module-level cached accessor
# --------------------------------------------------------------------------

_active_policy: Optional[ProtocolPolicy] = None


def get_active_policy() -> ProtocolPolicy:
    """Return a process-wide cached :class:`ProtocolPolicy`.

    The first call resolves :meth:`ProtocolPolicy.load`. Subsequent calls
    return the cached instance. Tests that need a custom policy should
    call :func:`set_active_policy` (typically via a pytest fixture) to
    swap it in.
    """
    global _active_policy
    if _active_policy is None:
        _active_policy = ProtocolPolicy.load()
    return _active_policy


def set_active_policy(policy: Optional[ProtocolPolicy]) -> None:
    """Swap (or clear) the cached policy. Pass ``None`` to reset."""
    global _active_policy
    _active_policy = policy


__all__ = [
    "ProtocolPolicy",
    "TierConfig",
    "CeremonyConfig",
    "RiskLimits",
    "CostModelConfig",
    "StressConfig",
    "DCAConfig",
    "ObjectiveConfig",
    "GAConfigPolicy",
    "PROTOCOL_VERSION",
    "get_active_policy",
    "set_active_policy",
]
