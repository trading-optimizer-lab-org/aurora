# `NotImplementedError` Classification (R53)

24 production-code sites raise `NotImplementedError`. Each falls into
one of three intentional categories. None are "unfinished work somebody
forgot to revisit" -- this document confirms that and ties each call
site to its category.

## Category A: Abstract base class declarations

These are deliberate `@abstractmethod`-style stubs in interface
definitions. Subclasses provide the implementation.

| Site | Interface |
|---|---|
| `core/data_providers/__init__.py:309` | `DataProvider.fetch` |
| `core/snapshots_distributed.py:69, 77, 82, 94, 102, 107` | `SnapshotBackend.{put_blob, get_blob, has_blob, put_metadata, get_metadata, list_metadata}` |
| `research/factory/factory.py:117` | `_AuditorProtocol.audit` |

8 sites total. **Do not remove** -- they enforce the interface
contract. Subclasses (`YahooProvider`, `LocalSnapshotBackend`,
`AgentAuditor`) override every one.

## Category B: Reserved-for-future "fail loud" stubs

Sites that exist to refuse a misconfigured caller rather than
silently no-op. The roadmap explicitly tracks the future
implementation under a separate item.

| Site | Reserved for |
|---|---|
| `core/snapshots_distributed.py:224` | Remote backends (`s3`, `postgres`, `gcs`, `azure_blob`); future drivers add a per-driver module. |
| `exports/lean/live.py:123` | Default `cli_invoker` for the Lean live deploy gate. R1 closure shipped the gate; the actual Lean CLI invocation is operator-supplied. |

2 sites total. **Do not remove** -- they make a misconfigured deployment
fail loud at the boundary instead of swallowing the error.

## Category C: "Live feed not configured" guards

The cross-asset-class modules under `markets/` and `marketdata/` ship
as `mock-only` per [`docs/MODULE_STATUS.md`](MODULE_STATUS.md). The
`NotImplementedError` raises when a caller asks for live data instead
of synthetic test fixtures.

| Site | Asset class |
|---|---|
| `marketdata/auction_imbalance.py:65` | NYSE auction imbalance |
| `marketdata/dark_pool_prints.py:81` | FINRA TRF dark pool prints |
| `marketdata/taq_reconstruction.py:63` | TAQ tick reconstruction |
| `markets/bonds.py:45` | Bond curve |
| `markets/cef_premium.py:46` | Closed-end fund premium |
| `markets/commodities_physical.py:40` | Physical commodities |
| `markets/credit.py:45` | CDS curves |
| `markets/crypto_basis.py:42` | Crypto basis |
| `markets/etf_arbitrage.py:42` | ETF NAV arbitrage |
| `markets/forex.py:78` | FX |
| `markets/futures.py:47` | Futures |
| `markets/volatility_products.py:42` | VIX-family vol products |

12 sites total. **Do not remove** -- they refuse to fabricate
placeholder data when an operator forgets to wire the real feed.

## Category D: Source dispatch defaults

Two general "unknown source" sites:

| Site | Context |
|---|---|
| `core/data_layer.py:892` | Unknown `source` kw passed to a dispatcher. |
| `core/realtime.py:227` | Unknown `source` in the realtime polling adapter. |

2 sites total. **Do not remove** -- they enforce that the dispatcher
covers every documented source name.

## Total

8 (A) + 2 (B) + 12 (C) + 2 (D) = 24, matches the grep count.

## R53 closure

Every `NotImplementedError` in production code is intentional and
falls into one of the four categories above. R53 is closed.

Future maintenance: when a new `NotImplementedError` lands, add it
to the matching category here with the relevant rationale. A site
that does not fit any of the four categories is a bug and must be
either implemented or removed.
