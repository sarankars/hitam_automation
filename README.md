# HITAM answer-sheet exporter

`hitam eval` opens the HITAM MidEvaluation portal, signs in to a B.Tech
evaluation bundle, observes each student's real answer-sheet PDF request, and
writes the sheet numbers and clickable PDF links to Excel.

The tool only reads the evaluation pages. It does not edit marks, save an
evaluation, or finalize a bundle.

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

```bash
hitam eval
```

The command asks for User Code, Subject Code, Bundle No, and Bundle Key. The
Bundle Key is entered invisibly. The browser is visible by default.

The workbook is written to the current directory with a timestamped name such
as `hitam_24PC5CD04_123_20260905_101112.xlsx`.

Optional flags:

```bash
hitam eval --headless
hitam eval --output /absolute/path/bundle-links.xlsx
```

An explicitly selected output file is never overwritten. Choose a new path if
the file already exists.

## Troubleshooting

- `Playwright Chromium is not installed`: run `playwright install chromium`
  inside the active virtual environment.
- A validation step times out: confirm the User Code, Bundle No, and Bundle Key,
  and check that the account has access to the B.Tech evaluation portal.
- No PDF request is observed: confirm the Subject Code matches the bundle. The
  command verifies the subject against the real PDF URL returned by the portal.
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
