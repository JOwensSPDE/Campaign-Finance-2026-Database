#!/usr/bin/env python3
"""Append a non-overlapping campaign-finance reporting period to candidate data."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


DATE_FORMAT = "%m/%d/%Y"
MONEY_FIELDS = (
    "totalReceipts",
    "candidateLoans",
    "totalExpenditures",
    "itemizedTotal",
    "delawareTotal",
    "outsideTotal",
    "unitemizedOrOther",
)


def date(value: str) -> datetime:
    return datetime.strptime(value, DATE_FORMAT)


def period(candidate: dict) -> dict:
    return {
        "periodStart": candidate["periodStart"],
        "periodEnd": candidate["periodEnd"],
        "reportDate": candidate["reportDate"],
        "sourceFile": candidate["sourceFile"],
        "totalReceipts": candidate["totalReceipts"],
        "candidateLoans": candidate["candidateLoans"],
        "totalExpenditures": candidate["totalExpenditures"],
    }


def overlaps(left: dict, right: dict) -> bool:
    return date(left["periodStart"]) <= date(right["periodEnd"]) and date(right["periodStart"]) <= date(left["periodEnd"])


def donor_signature(donor: dict) -> tuple:
    return donor["date"], donor["name"], donor["address"], donor["amount"]


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: merge_period_reports.py CURRENT_JSON NEW_PERIOD_JSON OUTPUT_JSON")

    current_path, new_path, output_path = map(Path, sys.argv[1:])
    current = json.loads(current_path.read_text(encoding="utf-8"))
    new_data = json.loads(new_path.read_text(encoding="utf-8"))
    by_account = {c["account"]: c for c in current["candidates"] if c["account"]}
    matched = added = 0
    added_receipts = 0.0
    added_donors = 0

    for new_candidate in new_data["candidates"]:
        candidate = by_account.get(new_candidate["account"])
        new_period = period(new_candidate)
        if not candidate:
            new_candidate["current2026Receipts"] = new_candidate["totalReceipts"]
            new_candidate["filingPeriods"] = [new_period]
            new_candidate["sourceFiles"] = [new_candidate["sourceFile"]]
            current["candidates"].append(new_candidate)
            by_account[new_candidate["account"]] = new_candidate
            added += 1
            added_receipts += new_candidate["totalReceipts"]
            added_donors += len(new_candidate["donors"])
            continue

        existing_periods = candidate.get("filingPeriods") or [period(candidate)]
        conflicting = [p for p in existing_periods if overlaps(p, new_period)]
        if conflicting:
            raise ValueError(f"Overlapping report for account {candidate['account']}: {new_period}")

        existing_signatures = {donor_signature(d) for d in candidate["donors"]}
        new_signatures = {donor_signature(d) for d in new_candidate["donors"]}
        duplicates = existing_signatures & new_signatures
        if duplicates:
            raise ValueError(f"Duplicate transactions across periods for account {candidate['account']}: {len(duplicates)}")

        old_total = candidate["totalReceipts"]
        candidate["current2026Receipts"] = round(
            candidate.get("current2026Receipts", old_total) + new_candidate["totalReceipts"], 2
        )
        for field in MONEY_FIELDS:
            candidate[field] = round(candidate[field] + new_candidate[field], 2)
        candidate["donors"].extend(new_candidate["donors"])
        candidate["endingBalance"] = new_candidate["endingBalance"]
        candidate["reportDate"] = new_candidate["reportDate"]
        candidate["periodEnd"] = new_candidate["periodEnd"]
        candidate["sourceFile"] = new_candidate["sourceFile"]
        candidate["filingPeriods"] = existing_periods + [new_period]
        candidate["sourceFiles"] = candidate.get("sourceFiles", [existing_periods[-1]["sourceFile"]]) + [new_candidate["sourceFile"]]
        candidate["excludedRows"] = candidate.get("excludedRows", 0) + new_candidate.get("excludedRows", 0)
        candidate["reportedItemizedTotal"] = round(
            candidate.get("reportedItemizedTotal", candidate["itemizedTotal"] - new_candidate["itemizedTotal"])
            + new_candidate.get("reportedItemizedTotal", new_candidate["itemizedTotal"]),
            2,
        )
        candidate["itemizedReconciliationGap"] = round(candidate["reportedItemizedTotal"] - candidate["itemizedTotal"], 2)
        matched += 1
        added_receipts += new_candidate["totalReceipts"]
        added_donors += len(new_candidate["donors"])

    current["candidates"].sort(key=lambda c: (c["race"], c["candidate"]))
    current["generated"] = datetime.now().date().isoformat()
    current["candidateCoverage"] = (
        "Supplied 2025 annual, 2026 30-day primary and 2026 8-day primary reports, "
        "combined only across non-overlapping reporting periods"
    )
    output_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    print(
        f"Merged {matched} reports and added {added} new candidate record(s); "
        f"added ${added_receipts:,.2f} in receipts and {added_donors:,} itemized rows"
    )


if __name__ == "__main__":
    main()
