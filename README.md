# Spotlight Delaware Campaign Finance Explorer

A dependency-free static site for exploring Delaware's 2026 primary campaign-finance reports and candidate-associated spending by third-party advertisers. It can be hosted directly on GitHub Pages.

Outside-advertiser cards and search results open dedicated profiles that summarize candidate-attributed spending, preserve support/opposition labels and link back to the affected candidate profiles.

## Preview locally

From this folder, run:

```bash
python3 -m http.server 8000
```

Then open `http://localhost:8000`.

## Publish on GitHub Pages

1. Create a GitHub repository and add everything in this folder.
2. In the repository, open **Settings → Pages**.
3. Under **Build and deployment**, choose **Deploy from a branch**.
4. Choose your default branch and the `/ (root)` folder, then save.

No build command or third-party JavaScript service is required.

## Refresh the data

The extractor requires Poppler's `pdftotext`. Run:

```bash
python3 tools/extract_data.py "/path/to/Candidate Funds" data/campaign-finance.json
```

Review the extractor's reconciliation warnings, then reload the site. The parser reconciles text-extracted rows against the official Schedule A total because Delaware PDFs may expose amended or deleted records in their text layer.
For privacy, published contributor locations include only the reported city and state; street addresses and ZIP codes are removed from the generated JSON. Candidate middle names and initials are also omitted from public display names.

To combine non-overlapping 2025 annual-report totals with the current candidate data, first extract the annual reports to a separate JSON file, then run:

```bash
python3 tools/merge_annual_reports.py data/campaign-finance.json annual-2025.json data/campaign-finance-merged.json
```

The merge matches committees by account number, rejects overlapping reporting periods and duplicate transactions across periods, and leaves candidates without a matching annual filing unchanged.

Candidate pages separately display candidate-named Schedule D-1 loans received across the supplied, non-overlapping periods. Vendor-only debts are excluded; this figure represents loans received rather than the current outstanding loan balance.

Later non-overlapping reports, such as 8-day primary filings, can be appended with:

```bash
python3 tools/merge_period_reports.py data/campaign-finance.json eight-day.json data/campaign-finance-updated.json
```

This merge also matches by account number, rejects period overlaps and cross-period duplicate transactions, and uses the newest filing's ending balance.

Third-party advertiser filings are processed separately:

```bash
python3 tools/extract_outside_spending.py "/path/to/3PAs" data/campaign-finance.json data/outside-spending.json
```

The outside-spending extractor replaces originals with amendments for the same reporting period, collapses duplicate downloads, excludes non-2026 transactions and assigns candidate totals only when the filing provides a defensible candidate allocation. Review `reviewIssues` in the resulting JSON before publication; unresolved filing discrepancies are deliberately excluded from candidate totals.

PAC filings use a separate extractor so direct candidate-committee donations are not confused with independent spending:

```bash
python3 tools/extract_pac_spending.py "/path/to/PACs" data/campaign-finance.json pac-spending.json
python3 tools/merge_outside_groups.py data/outside-spending.json pac-spending.json data/outside-spending-updated.json
```

Only PACs reporting expenditures above zero are published. Identified direct PAC donations appear on PAC profiles but are excluded from the site's Additional Outside Spending totals to avoid counting the same money again when it appears in a candidate committee's Schedule A receipts.

## Source files

The current dataset includes the corrected Michael Alexander Smith 30-day primary filing for Friends of Michael Smith, account `01006478`.

The current third-party advertiser dataset covers supplied reports through Sept. 8, 2026. It contains three filing discrepancies: a Delaware Senate Majority Caucus Campaign Committee expenditure whose printed candidate shares exceed the payment; a Good Growth expenditure whose description conflicts with both the payment amount and the named candidate's district; and a second Good Growth entry listing 16 equal candidate shares against a payment sufficient for only 15. The first two rows are excluded from candidate totals. In the third, explicitly printed shares for candidates in this database are retained with a warning because their subtotal remains below the filed payment.
