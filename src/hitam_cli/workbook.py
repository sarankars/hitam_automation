"""Excel workbook generation for captured answer-sheet links."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .portal import AnswerSheet

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(color="FFFFFF", bold=True)


def write_workbook(answer_sheets: list[AnswerSheet], output_path: Path) -> Path:
    """Atomically write a formatted workbook and return its absolute path."""
    if not answer_sheets:
        raise ValueError("Cannot create a workbook without answer-sheet links.")

    output = output_path.expanduser().resolve()
    if output.suffix.lower() != ".xlsx":
        raise ValueError("Output file must use the .xlsx extension.")
    if output.exists():
        raise FileExistsError(f"Output file already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Answer sheets"
    sheet.append(["Sheet No", "PDF Link"])

    for cell in sheet[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for answer_sheet in answer_sheets:
        sheet.append([answer_sheet.sheet_no, answer_sheet.pdf_url])
        row = sheet.max_row
        sheet.cell(row=row, column=1).number_format = "@"
        link_cell = sheet.cell(row=row, column=2)
        link_cell.hyperlink = answer_sheet.pdf_url
        link_cell.style = "Hyperlink"

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:B{sheet.max_row}"
    sheet.column_dimensions["A"].width = 16
    sheet.column_dimensions["B"].width = 90
    sheet.row_dimensions[1].height = 22

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{output.stem}.", suffix=".xlsx", dir=output.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        workbook.save(temporary_path)
        os.replace(temporary_path, output)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    finally:
        workbook.close()

    return output
