# HITAM exam evaluation CLI

The CLI supports a two-stage evaluation workflow:

1. `hitam exam export` creates an Excel workbook containing every student sheet
   number and its observed answer-sheet PDF link.
2. You add question columns such as `Q1`, `Q2`, and `Q3` and enter every mark.
3. `hitam exam upload WORKBOOK.xlsx` validates the whole workbook against the
   live portal, asks for confirmation, and saves each student's marks.

The CLI never finalizes a bundle.

## Setup

Python 3.11 or newer is required.

```bash
cd /Users/srnk/Projects/sarankars/hitam_automation
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
playwright install chromium
```

## Usage

### Export answer-sheet details

```bash
hitam exam export
```

The command asks for User Code, Subject Code, Bundle No, and Bundle Key. The
Bundle Key is entered invisibly. The browser is visible by default.

The workbook is written to the current directory with a timestamped name such
as `hitam_24PC5CD04_123_20260905_101112.xlsx`.

The generated workbook contains an `Answer sheets` sheet with `Sheet No` and
`PDF Link` columns. Add all question columns after `PDF Link`. Question labels
such as `Q1` match portal question `1`; labels are matched without regard to
case or spaces.

Optional export flags:

```bash
hitam exam export --headless
hitam exam export --output /absolute/path/bundle-links.xlsx
```

An explicitly selected output file is never overwritten. The workbook stores
Subject Code and Bundle No in hidden metadata, but never stores User Code or
Bundle Key.

### Upload completed marks

```bash
hitam exam upload /absolute/path/bundle-links.xlsx
```

Upload asks for User Code and hidden Bundle Key. It then checks every student,
PDF link, question label, mark, and live maximum before changing anything.
Blank cells, formulas, text values, missing students, and out-of-range marks are
rejected.

After validation, type `UPLOAD` exactly when prompted. The command deliberately
overwrites the portal marks with the workbook values, saves one student at a
time, and stops immediately if a save fails. It reports how many earlier
students were saved; remote saves cannot be rolled back.

Use `--headless` to hide the browser:

```bash
hitam exam upload bundle-links.xlsx --headless
```

## Troubleshooting

- `Playwright Chromium is not installed`: run `playwright install chromium`
  inside the active virtual environment.
- Export validation times out: confirm User Code, Bundle No, and Bundle Key and
  check that the account has B.Tech evaluation access.
- No PDF request is observed: confirm the Subject Code matches the bundle. The
  command verifies the subject against the real PDF URL returned by the portal.
- Upload rejects question columns: make their headers match the live question
  numbers, for example `Q1`, `Q2`, or `Q2(a)`.
- Upload rejects an older workbook: create a new workbook with
  `hitam exam export`; workbooks from the former `hitam eval` command do not
  contain the required metadata.
- To watch the automation, omit `--headless`; visible mode is the default.

## Tests

```bash
python -m unittest discover -s tests
```

The normal suite uses no portal credentials. To additionally run the local
mock-browser flow after installing Chromium:

```bash
HITAM_RUN_BROWSER_TESTS=1 python -m unittest discover -s tests
```
