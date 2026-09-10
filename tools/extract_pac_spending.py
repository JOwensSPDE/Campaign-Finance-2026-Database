#!/usr/bin/env python3
"""Extract PAC expenditures and identify direct candidate-committee donations."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from extract_outside_spending import choose_reports, parse_report


# Exact committee/payee wording from the supplied PAC filings. A null candidate
# ID keeps identifiable recipients visible even when they are not in the primary
# candidate dataset.
RECIPIENTS = (
    ("rd28-carson", "Bill Carson", r"Committee to Elect Bill Carson"),
    ("rd36-shupe", "Bryan Shupe", r"Committee to Elect Bryan Shupe"),
    ("rd6-mulvihill", "Edward Mulvihill", r"Committee To Elect Edward Mulvihill"),
    ("sd1-cruce", "Dan Cruce", r"Dan Cruce for State Senate"),
    (None, "Carlie Carey", r"Friends of Carlie Carey"),
    ("sd12-poore", "Nicole Poore", r"Friends of Nicole Poore"),
    ("rd1-chukwoucha", "Nnamdi Chukwuocha", r"Friends of Nnamdi Chukwuocha"),
    ("rd2-bolden", "Stephanie Bolden", r"Friends Of Stephanie T\. Bolden"),
    ("sd14-hoffner", "Kyra Hoffner", r"Friends to Elect Kyra Hoffner"),
    ("rd19-williams", "Kim Williams", r"Kim Williams for State Representative"),
    ("trs-smith", "Michael Smith", r"Mike Smith for Delaware"),
    ("sd5-seigfried", "Raymond Seigfried", r"Ray Seigfried for Delaware Senate"),
    (None, "Lyndon Yearick", r"Yearick for Delaware"),
    (None, "Mark Pugh", r"Friends of Mark Pugh for Senate"),
    ("rd12-griffith", "Krista Griffith", r"Krista Griffith For Delaware"),
    ("sd7-mantzavinos", "Spiros Mantzavinos", r"Spiros Mantzavinos for the 7th"),
    (None, "Anton Brogden", r"People for Anton Brogden"),
    (None, "Edward Osienski", r"Campaign to Elect Osienski"),
    ("rd16-cooke", "Franklin Cooke Jr", r"Citizens for Frank Cooke"),
    ("rd23-redlawsk", "David Redlawsk", r"Committee to Elect David Redlawsk"),
    ("rd20-berry", "Alonna Berry", r"Friends of Alonna Berry"),
    (None, "Claire Snyder-Hall", r"Friends of Claire Snyder-Hall"),
    ("rd27-morrison", "Eric Morrison", r"Friends of Eric Morrison"),
    ("ag-jennings", "Kathleen Jennings", r"Friends of Kathy Jennings"),
    ("rd32-evelyn-smith", "Kerri Harris", r"Friends of Kerri Evelyn Harris"),
    (None, "Mara Gorman", r"Friends of Mara Gorman"),
    (None, "Rajalakshmi Lodhavia", r"Friends of Nisha Lodhavia"),
    (None, "Theodore Lauzen", r"Lauzen for Delaware"),
    ("sd9-walsh", "John Walsh", r"Walsh for the 9th"),
    (None, "Brian Pettyjohn", r"Friends for Brian Pettyjohn"),
    ("rd19-inmbrie-moore", "William Imbrie-Moore", r"Friends of Will Imbrie-Moore"),
    ("rd20-schaeffer", "Ruby Schaeffer", r"Friends of Ruby Keeler Schaeffer"),
    ("rd27-muntz", "Eric Muntz", r"Muntz For NCC RD 27"),
    ("rd3-ortega", "Josue Ortega", r"Committee to Elect Josue Ortega"),
    ("ncc4-linton", "Curtis Linton", r"Friends of Curtis Linton"),
    ("ncc5-george", "Valerie George", r"Friends of Valerie George"),
    ("nccd-tackett", "David Tackett", r"The Committee to Elect David Tackett"),
    ("sd1-cruce", "Dan Cruce", r"Friends of Dan Cruce"),
    ("rd8-taylor", "Gary Taylor", r"Friends for Gary Taylor"),
    (None, "Matt Powell", r"Friends of Matt Powell"),
    (None, "Eric Buckson", r"Eric Buckson for State Senate"),
    (None, "Gerald Hocker", r"Friends To Elect Gerald Hocker"),
    (None, "Bryant Richardson", r"Richardson for State Senate"),
    (None, "Thompson For Delaware", r"Thompson For Delaware"),
    (None, "Andy Gorlich", r"Friends for Andy Gorlich"),
    (None, "Ryan Stuckey", r"Friends of Ryan Stuckey"),
    (None, "Joshua Pennington", r"Joshua Pennington for District 33"),
    (None, "Lindner4Delaware", r"Lindner4Delaware"),
    (None, "Madden for Delaware", r"Madden for Delaware"),
    (None, "Norman", r"\bNorman\b"),
)


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: extract_pac_spending.py PDF_DIR CANDIDATE_JSON OUTPUT_JSON")
    pdf_dir, candidate_path, output_path = map(Path, sys.argv[1:])
    reports = [parse_report(pdf) for pdf in sorted(pdf_dir.glob("*.pdf"))]
    selected, excluded = choose_reports(reports)
    candidate_ids = {
        c["id"] for c in json.loads(candidate_path.read_text(encoding="utf-8"))["candidates"]
    }
    compiled = [(cid, name, re.compile(pattern, re.I)) for cid, name, pattern in RECIPIENTS]
    positive = [report for report in selected if report["reportedTotal"] > 0]
    for report in selected:
        if report["reportedTotal"] <= 0:
            excluded.append({
                "sourceFile": report["sourceFile"],
                "reason": "PAC reported no expenditures",
            })

    allocations = []
    issues = []
    for report in positive:
        parsed_total = round(sum(row["amount"] for row in report["expenditures"]), 2)
        if abs(parsed_total - report["reportedTotal"]) > .01:
            issues.append({
                "account": report["account"],
                "sourceFile": report["sourceFile"],
                "reason": "Itemized expenditure rows do not equal the reported Schedule B total; the difference remains unattributed.",
                "amount": round(report["reportedTotal"] - parsed_total, 2),
            })
        for index, row in enumerate(report["expenditures"]):
            matches = [(cid, name) for cid, name, pattern in compiled if pattern.search(row["rawText"])]
            if len(matches) != 1:
                if len(matches) > 1:
                    issues.append({
                        "account": report["account"],
                        "sourceFile": report["sourceFile"],
                        "reason": "PAC expenditure matched multiple candidate committees and was left unattributed.",
                        "amount": row["amount"],
                        "rawText": row["rawText"],
                    })
                continue
            candidate_id, candidate_name = matches[0]
            if candidate_id and candidate_id not in candidate_ids:
                candidate_id = None
            allocations.append({
                "id": f"pac-{report['account']}-{index}-{row['date'].replace('/', '')}",
                "candidateId": candidate_id,
                "candidateName": candidate_name,
                "targetCandidateId": None,
                "position": "support",
                "allocationType": "direct-pac-contribution",
                "amount": row["amount"],
                "date": row["date"],
                "organization": report["organization"],
                "account": report["account"],
                "activity": "Direct PAC donation",
                "payee": row["payee"],
                "sourceFile": report["sourceFile"],
                "reportPeriodEnd": report["periodEnd"],
                "note": "PAC expenditure paid directly to the named candidate committee.",
            })

    groups = []
    for account in sorted({report["account"] for report in positive}):
        account_reports = [report for report in positive if report["account"] == account]
        groups.append({
            "account": account,
            "organization": account_reports[0]["organization"],
            "entityType": "PAC",
            "reportedExpenditures": round(sum(r["reportedTotal"] for r in account_reports), 2),
            "candidateAttributed": round(sum(a["amount"] for a in allocations if a["account"] == account), 2),
            "reportCount": len(account_reports),
        })

    payload = {
        "generated": datetime.now().date().isoformat(),
        "methodology": "Only PACs reporting expenditures above zero are public. Direct candidate-committee donations are identified separately from independent outside spending.",
        "groups": groups,
        "allocations": allocations,
        "reviewIssues": issues,
        "excludedReports": excluded,
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Parsed {len(reports)} PAC reports; published {len(groups)} with reported spending")
    print(f"Identified {len(allocations)} direct PAC donations totaling ${sum(a['amount'] for a in allocations):,.2f}")
    print(f"Excluded {sum(r['reportedTotal'] <= 0 for r in selected)} zero-spending PAC reports")


if __name__ == "__main__":
    main()
