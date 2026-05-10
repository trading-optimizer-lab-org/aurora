# Aurora Extension API (R186)

Aurora ships with a versioned local extension contract for the
following pluggable surfaces:

- DataProvider
- Strategy
- Signal
- Feature
- Validator
- BrokerAdapter
- ExecutionModel
- RiskModel
- ReportRenderer
- AuditSink

The contract is **path-only**, **opt-in**, and intentionally lacks a
marketplace, public registry, or remote loader. Extensions live in
directories you (the operator) explicitly add to
`$AU_EXTENSION_DIRS`. Anything outside that allowlist is refused at
load time.

## Discovery model

1. Set `AU_EXTENSION_DIRS=/path/one:/path/two` (Windows uses `;`).
2. Place files matching `*_aurora_ext.py` in those dirs.
3. Each file declares one extension descriptor:

```python
__aurora_extension__ = {
    "name": "...",
    "kind": "DataProvider",
    "interface_version": "1.0.0",
    "factory": MyClass,           # zero-arg callable
    "capabilities": {},           # forbidden flags refused
}
```

4. Call `aurora.core.extension_loader.discover_extensions()` to scan,
   or `load_extension(path)` for a single file.
5. `register_loaded_extensions(extensions)` pushes the descriptor into
   the matching Aurora registry.

What is intentionally **OFF**:

- No PyPI / entry-point discovery.
- No remote / network loading.
- No central marketplace or public registry.
- No autoload from `cwd`. The allowlist is the only entry point.

## Minimal local DataProvider

```python
# my_provider_aurora_ext.py
from typing import Any, Optional

import pandas as pd
from aurora.core.data_providers import BaseDataProvider


class MyProvider(BaseDataProvider):
    name = "my_provider"
    version = "my:0.1"
    point_in_time = True
    tier_permission = "IS_TRAIN"
    interface_version = "1.0.0"

    def _fetch_raw(self, symbol: str, start: Optional[pd.Timestamp],
                   end: Optional[pd.Timestamp], **kwargs: Any) -> pd.Series:
        return pd.Series(
            [100.0, 101.0, 102.0],
            index=pd.date_range("2024-01-01", periods=3, freq="B"),
            name=symbol,
        )


__aurora_extension__ = {
    "name": "my_provider",
    "kind": "DataProvider",
    "interface_version": "1.0.0",
    "factory": MyProvider,
    "capabilities": {"point_in_time": True},
}
```

## Minimal local Strategy

```python
# my_strategy_aurora_ext.py
import numpy as np
import pandas as pd

from aurora.strategies.base import Strategy, StrategySpec


class MyStrategy(Strategy):
    interface_version = "1.0.0"

    def signals(self, prices: pd.Series) -> np.ndarray:
        return np.zeros(len(prices))


__aurora_extension__ = {
    "name": "my_strategy",
    "kind": "Strategy",
    "interface_version": "1.0.0",
    "factory": lambda: MyStrategy,
    "capabilities": {},
}
```

## Invariants the extension cannot bypass

These flags in `capabilities` are **rejected** at load time. The loader
raises `ExtensionLoadError` on any of them set to `True`:

| Flag                       | Why it is forbidden |
|----------------------------|---------------------|
| `bypass_oosguard`          | OOSGuard is the locked-tier perimeter. An extension that opts out can leak future data into validation. |
| `bypass_audit`             | The hash-chained `AgentAudit` log is the only durable record of agent / extension actions. |
| `bypass_provider_terms`    | R178 ProviderTermsRegistry encodes operator-reviewed licence posture. Skipping it can authorise live trading on personal-use-only data. |
| `skip_validation_gates`    | The 9 mandatory gates in `validation.pipeline` are required by ProtocolPolicy. |

Extensions that need elevated tier access must use the existing
`OOSGuard("explicit_unlock_*")` ceremonies; they do not get a back door.

## Compatibility / deprecation policy

| Interface       | current | min_supported | deprecated_after | removed_after |
|-----------------|---------|---------------|------------------|---------------|
| DataProvider    | 1.0.0   | 1.0.0         | 2.0.0            | 3.0.0         |
| Strategy        | 1.0.0   | 1.0.0         | 2.0.0            | 3.0.0         |
| Signal          | 1.0.0   | 1.0.0         | 2.0.0            | 3.0.0         |
| Feature         | 1.0.0   | 1.0.0         | 2.0.0            | 3.0.0         |
| Validator       | 1.0.0   | 1.0.0         | 2.0.0            | 3.0.0         |
| BrokerAdapter   | 1.0.0   | 1.0.0         | 2.0.0            | 3.0.0         |
| ExecutionModel  | 1.0.0   | 1.0.0         | 2.0.0            | 3.0.0         |
| RiskModel       | 1.0.0   | 1.0.0         | 2.0.0            | 3.0.0         |
| ReportRenderer  | 1.0.0   | 1.0.0         | 2.0.0            | 3.0.0         |
| AuditSink       | 1.0.0   | 1.0.0         | 2.0.0            | 3.0.0         |

Rules:

- Bumping `current` is a source change in the in-tree implementation.
- Bumping `min_supported` is an EXTERNAL break: any extension older
  than the new floor stops loading and must be migrated.
- Major-version greater than `current` is refused (forward-compat is
  not silent: callers see `IncompatibleInterfaceError`).
- Pre-release / build metadata (`-rc.1`, `+sha.abc`) is allowed and
  ignored for ordering.

## Errors

| Exception                    | Cause |
|------------------------------|-------|
| `ExtensionPathBlocked`       | Path is not inside `AU_EXTENSION_DIRS`. |
| `IncompatibleInterfaceError` | `interface_version` outside the supported window or missing entirely. |
| `ExtensionLoadError`         | Descriptor missing required keys, factory not callable, or forbidden capability flag set. |

All three derive from `Exception`. The loader logs a warning and
**skips** the file during `discover_extensions`; for `load_extension`
the exception propagates so the caller can react.
