#!/usr/bin/env python3
"""Extract and classify Delaware third-party advertiser expenditures.

The state PDFs expose vendor payments in Schedule B. Candidate allocations are
derived only from explicit descriptions in the filings; ambiguous overhead and
multi-candidate payments stay unassigned until reviewed.
"""

from __future__ import annotations

import json
import hashlib
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


MONEY_RE = re.compile(r"\$([\d,]+\.\d{2})")
DATE_RE = re.compile(r"^\s*(\d{2}/\d{2}/\d{4})\s{2,}(.*)$")

# Candidate spellings seen in the filings. Patterns are intentionally narrow so
# a surname such as "Smith" cannot be assigned without office/race context.
CANDIDATE_PATTERNS = {
    "rd1-chukwoucha": r"(?:Nnamdi\s+)?(?:Chukwuocha|Chukwoucha|Chuwuocha|Chuckwuocha)",
    "rd1-darby": r"Shane(?:\s+Nicole)?\s+Darby",
    "rd2-bolden": r"Stephanie(?:\s+T\.)?\s+Bolden",
    "rd2-booker": r"Michelle\s+Booker",
    "rd3-ortega": r"Josue\s+(?:O\s+)?Ortega",
    "rd3-mccoy": r"Yolanda(?:\s+Marie)?\s+McCoy",
    "rd6-mulvihill": r"(?:Ed|Edward)\s+Mulvihill",
    "rd12-griffith": r"Krista\s+Griffith",
    "rd12-bahnsen": r"(?:Rob|Robert)\s+Bahnsen",
    "rd16-cooke": r"(?:Frank|Franklin)(?:\s+D\.?)?\s+Cooke(?:\s+Jr\.?)?",
    "rd19-williams": r"Kim\s+Williams",
    "rd20-berry": r"Alonna\s+Berry",
    "rd20-schaeffer": r"Ruby(?:\s+Keeler)?\s+Schaeffer",
    "rd23-redlawsk": r"(?:David\s+)?Redlawsk",
    "rd23-seador": r"Dan\s+Seador",
    "rd27-morrison": r"(?:Eric\s+)?Morrison",
    "rd28-carson": r"(?:Bill|William)\s+Carson",
    "rd28-grier": r"Tyeisha(?:\s+Nicole)?\s+Grier",
    "rd32-evelyn-smith": r"Kerri(?:\s+Evelyn|\s+Evenlyn)?\s+Harris",
    "rd32-paul": r"Lachelle(?:\s+D\.?)?\s+Paul",
    "ncc4-linton": r"Curtis(?:\s+Dauntell)?\s+Linton",
    "sd1-bohm": r"Adriana(?:\s+Leela)?\s+Bohm",
    "sd1-cruce": r"(?:Dan|San)\s+Cruce",
    "sd5-seigfried": r"(?:Ray|Raymond)\s+Seigfried",
    "sd7-mantzavinos": r"Spiros\s+Mantzavinos",
    "sd9-walsh": r"(?:Jack|John)\s+Walsh",
    "sd12-poore": r"Nicole\s+Poore",
    "sd12-watson": r"(?:Dr\.\s*)?Keonna\s+Watson",
    "sd14-hoffner": r"Kyra\s+Hoffner",
    "trs-smith": r"Michael(?:\s+Alexander)?\s+Smith",
    "ag-jennings": r"Kathleen\s+Jennings",
}

# Rows that allocate one vendor payment among multiple named candidates.
# The anomalous 08/03 Senate caucus row is deliberately omitted: its printed
# candidate shares total $25,001 while the filed expenditure is $22,772.
SPLIT_ALLOCATIONS = {
    ("04003188", "08/12/2026", 8000000): [
        ("rd1-chukwoucha", 820000), ("rd19-williams", 1280000),
        ("rd27-morrison", 820000), ("rd32-evelyn-smith", 820000),
        ("sd7-mantzavinos", 1470000), ("sd9-walsh", 1280000),
        ("sd12-poore", 1510000),
    ],
    ("04003188", "08/21/2026", 2732749): [
        ("rd19-williams", 376266), ("rd32-evelyn-smith", 231246),
        ("rd23-redlawsk", 341275), ("sd7-mantzavinos", 558954),
        ("sd9-walsh", 511720), ("sd12-poore", 713288),
    ],
    ("04003188", "09/02/2026", 3006674): [
        ("rd19-williams", 342232), ("rd32-evelyn-smith", 292192),
        ("rd23-redlawsk", 398572), ("sd7-mantzavinos", 615292),
        ("sd9-walsh", 570832), ("sd12-poore", 787554),
    ],
    ("04005615", "06/26/2026", 2500000): [
        ("sd1-cruce", 500000), ("sd5-seigfried", 500000),
        ("sd7-mantzavinos", 500000), ("sd12-poore", 500000),
        ("sd14-hoffner", 500000),
    ],
    ("04005615", "08/03/2026", 4000000): [
        ("sd5-seigfried", 1100000), ("sd9-walsh", 1100000),
        ("sd12-poore", 700000), ("sd14-hoffner", 1100000),
    ],
    ("04005615", "08/25/2026", 4863300): [
        ("sd1-cruce", 1495400), ("sd5-seigfried", 510300),
        ("sd7-mantzavinos", 437600), ("sd9-walsh", 905600),
        ("sd12-poore", 524800), ("sd14-hoffner", 989600),
    ],
    ("04005615", "09/08/2026", 2228500): [
        ("sd1-cruce", 747700), ("sd5-seigfried", 510300),
        ("sd9-walsh", 445700), ("sd12-poore", 524800),
    ],
    ("04006723", "08/24/2026", 439500): [
        ("rd3-ortega", 219750), ("rd3-mccoy", 219750),
    ],
}

RACE_OPPONENTS = {
    "rd1-darby": "rd1-chukwoucha",
    "rd12-bahnsen": "rd12-griffith",
    "sd12-watson": "sd12-poore",
    "rd28-grier": "rd28-carson",
    "sd1-bohm": "sd1-cruce",
}

# These filings identify supported candidates but do not provide a defensible
# candidate-by-candidate division of the reported expenditure total.
UNALLOCATED_CANDIDATE_SUPPORT = {
    "04005597": [
        "rd1-darby", "rd6-krantz", "rd16-salaam",
        "rd19-inmbrie-moore", "sd1-bohm", "sd5-frisby",
    ],
}


def money(value: str) -> float:
    return float(value.replace(",", ""))


def field(text: str, label: str) -> str:
    match = re.search(rf"{re.escape(label)}\s*:\s*(.+?)(?:\s{{3,}}|$)", text, re.M)
    return match.group(1).strip() if match else ""


def schedule_total(text: str) -> float:
    match = re.search(r"SCHEDULE B\s*-\s*TOTAL EXPENDITURES.*?\$([\d,]+\.\d{2})", text)
    return money(match.group(1)) if match else 0.0


def clean_block(lines: list[str]) -> str:
    cleaned = []
    for line in lines:
        value = " ".join(line.split())
        if not value or any(marker in value for marker in (
            "Campaign Finance", "Printed on", "Current Amended", "CFFM011",
            "Document: 14904", "Page ", "Date Expended Payee Name",
        )):
            continue
        cleaned.append(value)
    return " | ".join(cleaned)


def schedule_b_rows(text: str) -> list[dict]:
    starts = [m.start() for m in re.finditer("SCHEDULE B - TOTAL EXPENDITURES", text)]
    if not starts:
        return []
    start = starts[1] if len(starts) > 1 else starts[0]
    end_match = re.search(r"SCHEDULE C-1 - TOTAL IN-KIND RECEIPTS", text[start:])
    section = text[start:start + end_match.start()] if end_match else text[start:]
    entries: list[dict] = []
    current = None
    for line in section.splitlines():
        match = DATE_RE.match(line)
        if match:
            if current:
                current["rawText"] = clean_block(current.pop("lines"))
                entries.append(current)
            date, rest = match.groups()
            amounts = MONEY_RE.findall(rest)
            amount = money(amounts[-1]) if amounts else 0.0
            aggregate = money(amounts[-2]) if len(amounts) > 1 else None
            before_money = MONEY_RE.split(rest, maxsplit=1)[0]
            payee = re.split(r"\s{2,}", before_money.strip())[0].strip()
            current = {"date": date, "payee": payee, "aggregate": aggregate,
                       "amount": amount, "lines": [line]}
        elif current:
            if "TOTAL ITEMIZED EXPENDITURES" in line:
                current["rawText"] = clean_block(current.pop("lines"))
                entries.append(current)
                current = None
                break
            current["lines"].append(line)
    return entries


def parse_report(pdf: Path) -> dict:
    text = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"], check=True,
        capture_output=True, text=True,
    ).stdout
    first_page = text.split("\f", 1)[0]
    version = re.search(r"Document:\s*14904\s+Version:\s*(\d+)", text)
    return {
        "sourceFile": pdf.name,
        "organization": field(first_page, "FULL ORGANIZATION NAME"),
        "account": field(first_page, "ACCOUNT NUMBER"),
        "reportDate": field(first_page, "DATE OF THIS REPORT"),
        "periodStart": field(first_page, "REPORTING PERIOD START"),
        "periodEnd": field(first_page, "REPORTING PERIOD END"),
        "amended": bool(re.search(r"AMENDMENT\s*:\s*R YES", first_page)),
        "version": int(version.group(1)) if version else 1,
        "reportedTotal": schedule_total(text),
        "expenditures": schedule_b_rows(text),
    }


def choose_reports(reports: list[dict]) -> tuple[list[dict], list[dict]]:
    """Replace original reports with amendments and collapse duplicate downloads."""
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for report in reports:
        groups.setdefault((report["account"], report["periodStart"], report["periodEnd"]), []).append(report)
    selected, excluded = [], []
    for group in groups.values():
        amendments = [r for r in group if r["amended"]]
        pool = amendments or group
        ordered = sorted(
            pool,
            key=lambda r: (r["version"], r["reportDate"], r["sourceFile"]),
            reverse=True,
        )
        selected.append(ordered[0])
        selected_signature = tuple(
            (x["date"], x["payee"], x["amount"], x["rawText"])
            for x in ordered[0]["expenditures"]
        )
        for report in ordered[1:]:
            signature = tuple(
                (x["date"], x["payee"], x["amount"], x["rawText"])
                for x in report["expenditures"]
            )
            reason = (
                "duplicate report download"
                if signature == selected_signature
                else "superseded by later amendment"
            )
            excluded.append({"sourceFile": report["sourceFile"], "reason": reason})
        for report in group:
            if report not in pool:
                excluded.append({"sourceFile": report["sourceFile"], "reason": "superseded by amended report"})
    return selected, excluded


def activity(text: str) -> str:
    lower = text.lower()
    if "television" in lower:
        return "Television advertising"
    if "digital" in lower:
        return "Digital advertising"
    if "direct mail" in lower or "mail" in lower or "print" in lower:
        return "Mail"
    if "poll" in lower or "survey" in lower:
        return "Polling or survey"
    return "Candidate-associated expenditure"


def classify(reports: list[dict], candidate_ids: set[str]) -> tuple[list[dict], list[dict]]:
    allocations, issues = [], []
    compiled = {cid: re.compile(pattern, re.I) for cid, pattern in CANDIDATE_PATTERNS.items()}
    for report in reports:
        for index, row in enumerate(report["expenditures"]):
            if not row["date"].endswith("/2026"):
                continue
            source_key = hashlib.sha1(report["sourceFile"].encode()).hexdigest()[:8]
            row_id = f"{report['account']}-{source_key}-{index}"
            search_text = row["rawText"].replace("|", " ")
            split = SPLIT_ALLOCATIONS.get((report["account"], row["date"], round(row["amount"] * 100)))
            if report["account"] == "04006723" and round(row["amount"] * 100) == 2377650:
                if "Bryan" in search_text:
                    split = [(cid, 158510) for cid in (
                        "sd1-cruce", "sd5-seigfried", "sd7-mantzavinos",
                        "sd9-walsh", "sd12-poore", "sd14-hoffner",
                    )]
                elif "Melissa" in search_text:
                    split = [(cid, 158510) for cid in (
                        "rd32-evelyn-smith", "rd1-chukwoucha", "rd2-bolden",
                        "rd12-griffith", "rd16-cooke", "rd19-williams", "rd28-carson",
                    )]
                    issues.append({"sourceFile": report["sourceFile"], "rowId": row_id,
                                   "reason": "The filing lists 16 candidate shares of $1,585.10 ($25,361.60) against a $23,776.50 expenditure; individually printed shares for candidates in this database are retained with a warning.",
                                   "amount": row["amount"], "rawText": row["rawText"]})
            if split:
                for candidate_id, cents in split:
                    if candidate_id in candidate_ids:
                        allocations.append({
                            "id": f"{row_id}-{candidate_id}", "candidateId": candidate_id,
                            "targetCandidateId": None,
                            "position": "associated" if report["account"] in {"04003188", "04005615"} else "support",
                            "amount": cents / 100, "date": row["date"],
                            "organization": report["organization"], "account": report["account"],
                            "activity": activity(row["rawText"]), "payee": row["payee"],
                            "sourceFile": report["sourceFile"], "reportPeriodEnd": report["periodEnd"],
                            "note": ("The candidate's printed share is retained, but the filing's full allocation list does not reconcile to the payment."
                                     if report["account"] == "04006723" and "Melissa" in search_text
                                     else "Amount allocated among multiple candidates as itemized in the filing."),
                        })
                continue

            matches = [cid for cid, pattern in compiled.items() if pattern.search(search_text)]
            # A known filing error: four printed shares total $25,001 against a
            # $22,772 payment. It remains visible in issues but does not enter totals.
            if report["account"] == "04005615" and row["date"] == "08/03/2026" and round(row["amount"] * 100) == 2277200:
                issues.append({"sourceFile": report["sourceFile"], "rowId": row_id,
                               "reason": "Candidate allocations total $25,001, exceeding the $22,772 expenditure.",
                               "amount": row["amount"], "rawText": row["rawText"]})
                continue
            # Good Growth printed $6,335 in the description but $6,355 in both
            # expenditure columns and mislabeled Cruce's district as SD11.
            if report["account"] == "04006723" and round(row["amount"] * 100) == 635500:
                issues.append({"sourceFile": report["sourceFile"], "rowId": row_id,
                               "reason": "Description says $6,335 and SD11; expenditure columns say $6,355 and the named candidate is in SD1.",
                               "amount": row["amount"], "rawText": row["rawText"]})
                continue
            if len(matches) != 1:
                if matches:
                    issues.append({"sourceFile": report["sourceFile"], "rowId": row_id,
                                   "reason": "Multiple candidates named without a validated allocation.",
                                   "amount": row["amount"], "rawText": row["rawText"]})
                continue
            named = matches[0]
            opposing = bool(re.search(r"\boppos(?:e|ing|ition)\b", search_text, re.I))
            if opposing:
                beneficiary = RACE_OPPONENTS.get(named)
                if not beneficiary:
                    issues.append({"sourceFile": report["sourceFile"], "rowId": row_id,
                                   "reason": "Opposition spending cannot be mapped to one opponent.",
                                   "amount": row["amount"], "rawText": row["rawText"]})
                    continue
                candidate_id, target_id, position = beneficiary, named, "opposition-benefit"
            else:
                candidate_id, target_id = named, None
                position = "support" if re.search(r"\bsupport(?:ing)?\b", search_text, re.I) else "associated"
            if candidate_id not in candidate_ids:
                continue
            allocations.append({
                "id": f"{row_id}-{candidate_id}", "candidateId": candidate_id,
                "targetCandidateId": target_id, "position": position,
                "amount": row["amount"], "date": row["date"],
                "organization": report["organization"], "account": report["account"],
                "activity": activity(row["rawText"]), "payee": row["payee"],
                "sourceFile": report["sourceFile"], "reportPeriodEnd": report["periodEnd"],
                "note": "Opposition to the candidate's sole primary opponent." if opposing else "",
            })
    return allocations, issues


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: extract_outside_spending.py PDF_DIR CANDIDATE_JSON OUTPUT_JSON")
    reports = [parse_report(p) for p in sorted(Path(sys.argv[1]).glob("*.pdf"))]
    selected, excluded = choose_reports(reports)
    candidate_data = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    allocations, issues = classify(selected, {c["id"] for c in candidate_data["candidates"]})
    groups = []
    for account in sorted({r["account"] for r in selected}):
        organization_reports = [r for r in selected if r["account"] == account]
        group = {
            "account": account, "organization": organization_reports[0]["organization"],
            "reportedExpenditures": round(sum(r["reportedTotal"] for r in organization_reports if r["periodEnd"].endswith("/2026")), 2),
            "candidateAttributed": round(sum(a["amount"] for a in allocations if a["account"] == account), 2),
            "reportCount": len(organization_reports),
        }
        if account in UNALLOCATED_CANDIDATE_SUPPORT:
            group["unallocatedCandidateSupport"] = UNALLOCATED_CANDIDATE_SUPPORT[account]
            group["unallocatedSupportNote"] = (
                "The filings identify these candidates as supported but do not provide "
                "candidate-level amounts for the $455,000 in reported expenditures."
            )
        groups.append(group)
    payload = {
        "generated": datetime.now().date().isoformat(),
        "methodology": "Candidate totals include only explicit candidate allocations. Opposition spending is assigned as a benefit only in two-candidate races.",
        "groups": groups, "allocations": allocations, "reviewIssues": issues,
        "excludedReports": excluded,
    }
    Path(sys.argv[3]).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Parsed {len(reports)} reports; selected {len(selected)}; excluded {len(excluded)}")
    print(f"Created {len(allocations)} candidate allocations totaling ${sum(a['amount'] for a in allocations):,.2f}")
    print(f"Flagged {len(issues)} allocation issues")
    for report in reports:
        parsed = round(sum(row["amount"] for row in report["expenditures"]), 2)
        if abs(parsed - report["reportedTotal"]) > .01:
            difference = round(report["reportedTotal"] - parsed, 2)
            if difference < -0.01:
                print(f"MISMATCH {report['sourceFile']}: reported {report['reportedTotal']:.2f}, parsed {parsed:.2f}")


if __name__ == "__main__":
    main()
