#!/usr/bin/env python3
"""Merge non-overlapping annual-report totals into the current candidate dataset."""

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
    "smallContributionsTotal",
    "unitemizedOrOther",
)


def date(value: str) -> datetime:
    return datetime.strptime(value, DATE_FORMAT)


def donor_signature(donor: dict) -> tuple:
    return donor["date"], donor["name"], donor["address"], donor["amount"]


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(
            "usage: merge_annual_reports.py CURRENT_JSON ANNUAL_JSON OUTPUT_JSON"
        )

    current_path, annual_path, output_path = map(Path, sys.argv[1:])
    current = json.loads(current_path.read_text(encoding="utf-8"))
    annual = json.loads(annual_path.read_text(encoding="utf-8"))
    annual_by_account = {c["account"]: c for c in annual["candidates"] if c["account"]}

    matched = 0
    added_receipts = 0.0
    added_donors = 0
    for candidate in current["candidates"]:
        annual_candidate = annual_by_account.get(candidate["account"])
        if not annual_candidate:
            continue
        if candidate.get("annual2025Receipts") is not None:
            raise ValueError(f"{candidate['candidate']} already contains annual totals")
        if date(annual_candidate["periodEnd"]) >= date(candidate["periodStart"]):
            raise ValueError(
                f"Overlapping periods for account {candidate['account']}: "
                f"{annual_candidate['periodStart']}-{annual_candidate['periodEnd']} and "
                f"{candidate['periodStart']}-{candidate['periodEnd']}"
            )

        annual_signatures = {donor_signature(d) for d in annual_candidate["donors"]}
        current_signatures = {donor_signature(d) for d in candidate["donors"]}
        duplicates = annual_signatures & current_signatures
        if duplicates:
            raise ValueError(
                f"Duplicate transactions across periods for account {candidate['account']}: "
                f"{len(duplicates)}"
            )

        current_period = {
            "periodStart": candidate["periodStart"],
            "periodEnd": candidate["periodEnd"],
            "reportDate": candidate["reportDate"],
            "sourceFile": candidate["sourceFile"],
            "totalReceipts": candidate["totalReceipts"],
            "candidateLoans": candidate["candidateLoans"],
            "totalExpenditures": candidate["totalExpenditures"],
            "smallContributionsTotal": candidate.get("smallContributionsTotal", 0),
        }
        annual_period = {
            "periodStart": annual_candidate["periodStart"],
            "periodEnd": annual_candidate["periodEnd"],
            "reportDate": annual_candidate["reportDate"],
            "sourceFile": annual_candidate["sourceFile"],
            "totalReceipts": annual_candidate["totalReceipts"],
            "candidateLoans": annual_candidate["candidateLoans"],
            "totalExpenditures": annual_candidate["totalExpenditures"],
            "smallContributionsTotal": annual_candidate.get("smallContributionsTotal", 0),
        }

        candidate["annual2025Receipts"] = annual_candidate["totalReceipts"]
        candidate["current2026Receipts"] = candidate["totalReceipts"]
        candidate["filingPeriods"] = [annual_period, current_period]
        candidate["sourceFiles"] = [annual_candidate["sourceFile"], candidate["sourceFile"]]
        candidate["periodStart"] = annual_candidate["periodStart"]
        for field in MONEY_FIELDS:
            candidate[field] = round(candidate.get(field, 0) + annual_candidate.get(field, 0), 2)
        candidate["donors"] = annual_candidate["donors"] + candidate["donors"]
        candidate["smallContributionRows"] = annual_candidate.get("smallContributionRows", []) + candidate.get("smallContributionRows", [])
        candidate["excludedRows"] = candidate.get("excludedRows", 0) + annual_candidate.get("excludedRows", 0)
        candidate["reportedItemizedTotal"] = round(
            candidate.get("reportedItemizedTotal", candidate["itemizedTotal"] - annual_candidate["itemizedTotal"])
            + annual_candidate.get("reportedItemizedTotal", annual_candidate["itemizedTotal"]),
            2,
        )
        candidate["itemizedReconciliationGap"] = round(
            candidate["reportedItemizedTotal"] - candidate["itemizedTotal"], 2
        )

        matched += 1
        added_receipts += annual_candidate["totalReceipts"]
        added_donors += len(annual_candidate["donors"])

    current["generated"] = datetime.now().date().isoformat()
    current["candidateCoverage"] = (
        "2025 annual reports plus 2026 30-day primary reports where both were supplied; "
        "otherwise 2026 30-day primary reports only"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    print(
        f"Merged {matched} annual reports; added ${added_receipts:,.2f} in receipts "
        f"and {added_donors:,} itemized transaction rows"
    )


if __name__ == "__main__":
    main()
