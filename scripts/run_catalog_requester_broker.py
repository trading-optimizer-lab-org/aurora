"""Development-only adapter for the isolated requester broker."""

from aurora.infra.sp500_megarun.catalog_requester_broker_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
