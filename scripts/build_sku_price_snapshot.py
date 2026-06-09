#!/usr/bin/env python3
"""Offline CLI: build a SKU-backed ``local_cache`` snapshot from official AWS Price
List service offer files on local disk.

No network calls. No AWS credentials. The operator downloads the official offer
files once (e.g. from the AWS Price List bulk API) and points this at the local
paths; this tool reduces them into Archway's compact local-cache schema and stamps
provenance hashed over the raw official bytes.

Example:
    python scripts/build_sku_price_snapshot.py \\
        --region us-east-1 \\
        --output .archway/pricing/aws-price-list-us-east-1.json \\
        --offer AmazonS3=/path/to/AmazonS3/index.json \\
        --offer AWSLambda=/path/to/AWSLambda/index.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the repo root importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.sku_pricing.official_snapshot_builder import (  # noqa: E402
    SnapshotBuildError,
    build_snapshot_from_offer_files,
    write_local_cache_snapshot,
)


def _parse_offers(values: list[str] | None) -> dict[str, str]:
    offers: dict[str, str] = {}
    for item in values or []:
        if "=" not in item:
            raise SystemExit(f"--offer expects SERVICE=PATH, got {item!r}")
        code, path = item.split("=", 1)
        offers[code.strip()] = path.strip()
    return offers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build an offline SKU local_cache snapshot from official AWS Price List offer files.",
    )
    parser.add_argument("--region", required=True, help="AWS region code, e.g. us-east-1")
    parser.add_argument("--output", required=True, help="Output snapshot JSON path")
    parser.add_argument(
        "--offer",
        action="append",
        metavar="SERVICE=PATH",
        help="Repeatable. Official offer file path, e.g. AmazonS3=/path/index.json",
    )
    parser.add_argument("--snapshot-id", default=None, help="Optional explicit snapshot id")
    parser.add_argument("--source-url", default=None, help="Optional official source URL/identifier")
    args = parser.parse_args(argv)

    offers = _parse_offers(args.offer)
    if not offers:
        print("error: at least one --offer SERVICE=PATH is required", file=sys.stderr)
        return 2
    for code, path in offers.items():
        if not Path(path).is_file():
            print(f"error: offer file not found for {code}: {path}", file=sys.stderr)
            return 2

    try:
        snapshot, report = build_snapshot_from_offer_files(
            offers,
            region=args.region,
            snapshot_id=args.snapshot_id,
            upstream_source_url=args.source_url,
        )
    except SnapshotBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out = write_local_cache_snapshot(snapshot, args.output)
    print("SKU price snapshot built (offline, no network, no AWS credentials).")
    print(f"  region:          {report.region}")
    print(f"  services read:   {', '.join(report.services_read)}")
    print(f"  rates emitted:   {report.rates_emitted}")
    print(f"  skipped:         {len(report.skipped)}")
    print(f"  ambiguous:       {len(report.ambiguous)}")
    print(f"  source hash:     {report.source_hash}")
    print(f"  output:          {out}")
    for item in report.skipped:
        label = item.get("dimension_key") or item.get("service_code")
        print(f"    skip {label}: {item.get('reason')}")
    for item in report.ambiguous:
        print(f"    ambiguous {item.get('dimension_key')}: {item.get('candidate_skus')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
