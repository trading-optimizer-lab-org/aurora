"""Development-only adapter for the isolated requester client."""

from aurora.infra.sp500_megarun.catalog_requester_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
