#!/usr/bin/env python3
"""Merge PAC profiles into the existing outside-advertiser dataset."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: merge_outside_groups.py BASE_JSON PAC_JSON OUTPUT_JSON")
    base_path, pac_path, output_path = map(Path, sys.argv[1:])
    base = json.loads(base_path.read_text(encoding="utf-8"))
    pac = json.loads(pac_path.read_text(encoding="utf-8"))
    pac_accounts = {group["account"] for group in pac["groups"]}

    for group in base["groups"]:
        group.setdefault("entityType", "Third-party advertiser")
    for allocation in base["allocations"]:
        allocation.setdefault("allocationType", "independent-spending")

    base["groups"] = [g for g in base["groups"] if g["account"] not in pac_accounts] + pac["groups"]
    base["allocations"] = [a for a in base["allocations"] if a["account"] not in pac_accounts] + pac["allocations"]
    base["reviewIssues"] = [i for i in base.get("reviewIssues", []) if i.get("account") not in pac_accounts] + pac.get("reviewIssues", [])
    base["excludedReports"] = base.get("excludedReports", []) + pac.get("excludedReports", [])
    base["groups"].sort(key=lambda g: (g["entityType"], g["organization"]))
    base["allocations"].sort(key=lambda a: (a["account"], a["date"], a["id"]))
    base["generated"] = datetime.now().date().isoformat()
    base["methodology"] = (
        "Third-party advertiser allocations remain separate from candidate fundraising. "
        "Only PACs with reported expenditures above zero are public; direct PAC donations "
        "are identified separately and are not added to independent outside-spending totals."
    )
    output_path.write_text(json.dumps(base, indent=2), encoding="utf-8")
    print(f"Merged {len(pac['groups'])} PAC profiles and {len(pac['allocations'])} direct PAC donations")


if __name__ == "__main__":
    main()
