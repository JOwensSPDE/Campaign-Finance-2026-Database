#!/usr/bin/env python3
"""Extract Delaware campaign finance Schedule A records from state PDFs."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


MONEY = r"\$?\(?-?[\d,]+(?:\.\d{2})?\)?"
DATE_ROW = re.compile(
    rf"^\s*(\d{{2}}/\d{{2}}/\d{{4}})\s+(.*?)\s{{2,}}(.*?)\s{{2,}}({MONEY})\s+({MONEY})\s*$"
)

STATE_NAMES = {
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "District Of Columbia", "Florida", "Georgia",
    "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
    "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire",
    "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota",
    "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
    "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
    "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
}

SMALL_CONTRIBUTIONS_LABEL = "TOTAL OF CONTRIBUTIONS NOT EXCEEDING $100"


def is_small_contributions_total(name: str) -> bool:
    return name.strip().casefold().startswith(SMALL_CONTRIBUTIONS_LABEL.casefold())


def city_and_state(address: str) -> str:
    """Return only the reported city and state, omitting street and ZIP details."""
    parts = [part.strip() for part in address.split(",")]
    for index in range(len(parts) - 1, 0, -1):
        state = next(
            (name for name in STATE_NAMES if parts[index].casefold() == name.casefold()),
            None,
        )
        if state:
            city = next((part for part in reversed(parts[:index]) if part), "")
            if re.search(r"\d", city):
                return state
            return f"{city}, {state}" if city else state
    return ""


def public_candidate_name(name: str) -> str:
    """Omit candidate middle names and initials from the public dataset."""
    parts = name.split()
    if len(parts) <= 2:
        return name
    suffixes = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}
    if parts[-1].casefold() in suffixes and len(parts) >= 3:
        return " ".join((parts[0], parts[-2], parts[-1]))
    return " ".join((parts[0], parts[-1]))


def money(value: str) -> float:
    value = value.strip()
    negative = (value.startswith("(") and value.endswith(")")) or value.startswith("-")
    number = float(re.sub(r"[$,()\-]", "", value))
    return -number if negative else number


def field(text: str, label: str) -> str:
    match = re.search(rf"{re.escape(label)}\s*:\s*(.+?)(?:\s{{3,}}|$)", text, re.M)
    return match.group(1).strip() if match else ""


def amount_field(text: str, label_pattern: str) -> float:
    match = re.search(rf"{label_pattern}.*?(\(?-?\$[\d,]+\.\d{{2}}\)?)", text)
    return money(match.group(1)) if match else 0


def candidate_loans_received(text: str, candidate_name: str, reported_total: float) -> float:
    """Total Schedule D-1 rows whose named lender is the candidate.

    Schedule D-1 combines loans with other debts incurred. Restricting rows to the
    candidate's surname excludes vendor debts. The filed schedule total is used to
    reconcile duplicate/deleted PDF text layers when every reported row is a
    candidate row.
    """
    if not reported_total:
        return 0
    starts = [m.start() for m in re.finditer(
        r"SCHEDULE D-1\s*-\s*TOTAL LOANS RECEIVED AND DEBTS INCURRED", text, re.I
    )]
    if not starts:
        return 0
    start = starts[-1]
    end = text.find("SCHEDULE D-2", start)
    schedule = text[start:end if end >= 0 else None]
    surname = next(
        (part for part in reversed(candidate_name.split()) if part.casefold().rstrip(".") not in {"jr", "sr", "ii", "iii", "iv"}),
        "",
    )
    transaction_amounts = []
    candidate_amounts = []
    for line in schedule.splitlines():
        if not re.search(r"\b\d{2}/\d{2}/\d{4}\b", line):
            continue
        amounts = re.findall(MONEY, line)
        if not amounts:
            continue
        amount = money(amounts[-1])
        transaction_amounts.append(amount)
        if surname and re.search(rf"\b{re.escape(surname)}\b", line, re.I):
            candidate_amounts.append(amount)
    if not candidate_amounts:
        return 0
    if len(candidate_amounts) == len(transaction_amounts):
        return reported_total
    candidate_sum = round(sum(candidate_amounts), 2)
    return min(candidate_sum, reported_total)


def candidate_from_text(text: str, fallback: str) -> str:
    marker = text.find("CANDIDATE SIGNATURE")
    if marker >= 0:
        lines = [line.strip() for line in text[:marker].splitlines() if line.strip()]
        if lines:
            candidate = re.sub(r"^(Mr\.?|Ms\.?|Mrs\.?|Dr\.?)\s+", "", lines[-1]).strip()
            if candidate and len(candidate) < 80 and "SIGNATURE" not in candidate:
                return candidate
    return fallback


def reconcile_deleted_rows(donors: list[dict], reported_total: float) -> tuple[list[dict], list[dict]]:
    """Remove duplicate PDF layers and rows marked deleted in the source form.

    Delaware's generated PDFs sometimes expose deleted/amended rows to text extraction.
    The official Schedule A total is used as the reconciliation control.
    """
    collapsed = []
    for donor in donors:
        signature = (donor["date"], donor["name"], donor["address"], donor["amount"])
        is_unitemized_batch = donor["name"].casefold().startswith("total of contributions not exceeding")
        if collapsed and not is_unitemized_batch and signature == (
            collapsed[-1]["date"], collapsed[-1]["name"], collapsed[-1]["address"], collapsed[-1]["amount"]
        ):
            continue
        collapsed.append(donor)

    excess = round(sum(d["amount"] for d in collapsed) - reported_total, 2)
    if excess <= 0:
        return collapsed, []
    target = round(excess * 100)
    # Find an exact subset with the fewest rows; deleted rows are commonly reclassified entries.
    states: dict[int, tuple[int, ...]] = {0: ()}
    for index, donor in enumerate(collapsed):
        cents = round(donor["amount"] * 100)
        if cents <= 0 or cents > target:
            continue
        additions = {}
        for subtotal, chosen in list(states.items()):
            new_total = subtotal + cents
            if new_total <= target and (
                new_total not in states or len(chosen) + 1 < len(states[new_total])
            ):
                additions[new_total] = chosen + (index,)
        states.update(additions)
        if target in states:
            break
    if target not in states:
        return collapsed, []
    removed_indices = set(states[target])
    return (
        [d for i, d in enumerate(collapsed) if i not in removed_indices],
        [d for i, d in enumerate(collapsed) if i in removed_indices],
    )


def fallback_name(stem: str) -> str:
    prefixes = ["NCCD - ", "AG ", "TRS "]
    for prefix in prefixes:
        if stem.startswith(prefix):
            return stem[len(prefix):]
    return re.sub(r"^(?:NCC|RD|SD)\d+\s+", "", stem)


def race_from_filename(stem: str) -> tuple[str, str]:
    if stem.startswith("AG "):
        return "AG", "Attorney General"
    if stem.startswith("TRS "):
        return "TRS", "State Treasurer"
    if stem.startswith("NCCD"):
        return "NCCD", "New Castle County Recorder of Deeds"
    match = re.match(r"(NCC|RD|SD)(\d+)", stem)
    if not match:
        return stem, stem
    prefix, number = match.groups()
    labels = {
        "NCC": "New Castle County Council District",
        "RD": "State House District",
        "SD": "State Senate District",
    }
    return f"{prefix}{number}", f"{labels[prefix]} {number}"


def extract(pdf: Path) -> dict:
    text = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"], check=True, capture_output=True, text=True
    ).stdout
    first_page = text.split("\f", 1)[0]
    stem = pdf.stem
    race_id, race_name = race_from_filename(stem)

    starts = [m.start() for m in re.finditer("SCHEDULE A - TOTAL RECEIPTS", text)]
    start = starts[1] if len(starts) > 1 else (starts[0] if starts else 0)
    ends = [m.start() for m in re.finditer("SCHEDULE B - TOTAL EXPENDITURES", text)]
    end = next((position for position in ends if position > start), -1)
    schedule = text[start:end if end >= 0 else None]
    donors = []
    for line in schedule.splitlines():
        match = DATE_ROW.match(line)
        if not match:
            continue
        date, name, address, aggregate, received = match.groups()
        donors.append({
            "date": date,
            "name": " ".join(name.split()),
            "address": " ".join(address.split()),
            "aggregate": money(aggregate),
            "amount": money(received),
        })

    # Add wrapped address text immediately below a donor row, stopping before the next row/footer.
    lines = schedule.splitlines()
    donor_index = -1
    for line in lines:
        if DATE_ROW.match(line):
            donor_index += 1
            continue
        if donor_index < 0 or not line.strip():
            continue
        if any(token in line for token in ("Campaign Finance", "Printed on", "Current", "GRAND TOTAL")):
            continue
        # Address continuations occupy the address column and have no currency values.
        if not re.search(r"\$[\d,]", line) and len(line) > 55:
            continuation = line[55:132].strip()
            if continuation and not continuation.startswith(("Date Received", "Contributor Mailing")):
                donors[donor_index]["address"] = (donors[donor_index]["address"] + " " + continuation).strip()

    total_receipts = amount_field(first_page + "\n" + text[:8000], r"SCHEDULE A\s*-\s*TOTAL RECEIPTS")
    reported_itemized = amount_field(schedule, r"TOTAL ITEMIZED RECEIPTS")
    small_contributions = amount_field(
        schedule, r"TOTAL OF CONTRIBUTIONS NOT EXCEEDING \$100"
    )
    reconciliation_total = reported_itemized if reported_itemized or not donors else total_receipts
    donors, excluded_rows = reconcile_deleted_rows(donors, reconciliation_total)
    total_expenditures = amount_field(first_page + "\n" + text[:8000], r"SCHEDULE B\s*-\s*TOTAL EXPENDITURES")
    ending_balance = amount_field(first_page + "\n" + text[:8000], r"ENDING BALANCE")
    itemized = round(sum(d["amount"] for d in donors), 2)
    in_state = round(small_contributions + sum(
        d["amount"] for d in donors
        if is_small_contributions_total(d["name"])
        or re.search(r"\bDelaware\b", d["address"], re.I)
    ), 2)
    out_state = round(itemized - in_state, 2)
    for donor in donors:
        if is_small_contributions_total(donor["name"]):
            donor["name"] = SMALL_CONTRIBUTIONS_LABEL
            donor["address"] = "Delaware"
        else:
            donor["address"] = city_and_state(donor["address"])
    fallback = fallback_name(stem)
    name_overrides = {
        "AG Rickman": "Patricia Dawn Rickman",
        "NCC4 Hoover": "Jason Hoover",
        "NCC5 Kosigi": "Syam Kosigi",
        "NCCD - Kozikowski": "Michael Kozikowski",
        "RD1 Darby": "Shané Darby",
        "RD12 Bahnsen": "Robert Bahnsen",
        "RD12 Griffith": "Krista Griffith",
        "RD16 Salaam": "Pamela Salaam",
        "RD19 Williams": "Kim Williams",
        "RD20 Berry": "Alonna Berry",
        "RD20 Schaeffer": "Ruby Keeler Schaeffer",
        "RD23 DAgostino": "Luann D'Agostino",
        "RD23 Seador": "Dan Seador",
        "RD3 Graham": "LaDonna Graham",
        "RD3 McCoy": "Yolanda McCoy",
        "RD8 Moore": "Sherae'a Moore",
        "RD27 Muntz": "Eric Muntz",
        "RD28 Carson": "Bill Carson",
        "RD32 Evelyn Smith": "Kerri Evelyn Harris",
        "RD36 Smith": "Patrick Smith",
        "RD41 Atkins": "John Atkins",
        "RD6 Mulvihill": "Edward Mulvihill",
        "RD9 Khan Flowers": "Ayanna Khan-Flowers",
        "RD9 Lowery": "Gemma Lowery",
        "RD9 Wall": "Michelle Wall",
        "SD1 Cruce": "Dan Cruce",
        "SD14 Beardsley": "David Beardsley",
        "SD5 Frisby": "Shay Frisby",
        "SD7 Lopez": "Jose Lopez",
    }
    candidate_name = public_candidate_name(name_overrides.get(stem, candidate_from_text(first_page, fallback)))
    reported_loans = amount_field(
        first_page + "\n" + text[:8000],
        r"SCHEDULE D-1\s*-\s*TOTAL LOANS RECEIVED AND DEBTS INCURRED",
    )
    return {
        "id": re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-"),
        "candidate": candidate_name,
        "shortName": fallback,
        "committee": field(first_page, "FULL ORGANIZATION NAME"),
        "account": field(first_page, "ACCOUNT NUMBER"),
        "raceId": race_id,
        "race": race_name,
        "reportDate": field(first_page, "DATE OF THIS REPORT"),
        "periodStart": field(first_page, "REPORTING PERIOD START"),
        "periodEnd": field(first_page, "REPORTING PERIOD END"),
        "totalReceipts": total_receipts,
        "candidateLoans": candidate_loans_received(text, candidate_name, reported_loans),
        "totalExpenditures": total_expenditures,
        "endingBalance": ending_balance,
        "itemizedTotal": itemized,
        "smallContributionsTotal": small_contributions,
        "smallContributionRows": ([{
            "date": field(first_page, "REPORTING PERIOD END"),
            "name": SMALL_CONTRIBUTIONS_LABEL,
            "address": "Delaware",
            "aggregate": small_contributions,
            "amount": small_contributions,
            "receiptType": "aggregate-small-contributions",
        }] if small_contributions else []),
        "reportedItemizedTotal": reported_itemized,
        "itemizedReconciliationGap": round(reported_itemized - itemized, 2),
        "delawareTotal": in_state,
        "outsideTotal": out_state,
        "unitemizedOrOther": round(total_receipts - itemized - small_contributions, 2),
        "donors": donors,
        "excludedRows": len(excluded_rows),
        "sourceFile": pdf.name,
    }


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: extract_data.py PDF_DIR OUTPUT_JSON")
    pdf_dir, output = Path(sys.argv[1]), Path(sys.argv[2])
    extracted = [extract(pdf) for pdf in sorted(pdf_dir.glob("*.pdf"))]
    # Keep only the newest report when the supplied folder contains multiple reports
    # for the same committee account.
    by_account = {}
    for candidate in extracted:
        existing = by_account.get(candidate["account"])
        report_key = datetime.strptime(candidate["reportDate"], "%m/%d/%Y")
        existing_key = datetime.strptime(existing["reportDate"], "%m/%d/%Y") if existing else datetime.min
        if not existing or report_key > existing_key:
            by_account[candidate["account"]] = candidate
    candidates = sorted(by_account.values(), key=lambda c: (c["race"], c["candidate"]))
    payload = {
        "generated": "2026-09-01",
        "source": "Delaware campaign finance reports supplied by Spotlight Delaware",
        "candidates": candidates,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {len(candidates)} candidates and {sum(len(c['donors']) for c in candidates)} donor rows")
    for candidate in candidates:
        reconciliation_gap = candidate["itemizedReconciliationGap"]
        if abs(reconciliation_gap) > .01:
            print(f"{candidate['sourceFile']}: unreconciled itemized difference ${reconciliation_gap:,.2f}")
        gap = candidate["unitemizedOrOther"]
        if abs(gap) > 1:
            print(f"{candidate['sourceFile']}: itemized gap ${gap:,.2f}")


if __name__ == "__main__":
    main()
