import argparse

from services.filter import run_filter
from services.ingest import run_ingest
from services.mapping import run_mapping


def main() -> None:
    parser = argparse.ArgumentParser(description="Run backend pipeline steps")
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--skip-filter", action="store_true")
    parser.add_argument("--skip-mapping", action="store_true")
    parser.add_argument("--stock-id", type=str, default=None)
    args = parser.parse_args()

    if not args.skip_ingest:
        run_ingest()
    if not args.skip_filter:
        run_filter()
    if not args.skip_mapping:
        run_mapping(stock_id=args.stock_id)


if __name__ == "__main__":
    main()
