"""Browser automation for the HITAM MidEvaluation portal."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

PORTAL_URL = "https://hitamexams.org/MidEvaluation/"
DEFAULT_TIMEOUT_MS = 30_000
SHEET_NUMBER_PATTERN = re.compile(r"^\s*(\d{6})\s*$")


class PortalError(RuntimeError):
    """Raised when the portal cannot complete the requested read-only workflow."""


@dataclass(frozen=True)
class EvaluationInputs:
    user_code: str
    subject_code: str
    bundle_no: str
    bundle_key: str


@dataclass(frozen=True)
class AnswerSheet:
    sheet_no: str
    pdf_url: str


def normalise_inputs(
    user_code: str,
    subject_code: str,
    bundle_no: str,
    bundle_key: str,
) -> EvaluationInputs:
    """Trim and validate values collected by the CLI."""
    values = {
        "User Code": user_code.strip(),
        "Subject Code": subject_code.strip().upper(),
        "Bundle No": bundle_no.strip(),
        "Bundle Key": bundle_key.strip(),
    }
    missing = [label for label, value in values.items() if not value]
    if missing:
        raise ValueError(f"Required value is empty: {', '.join(missing)}")
    return EvaluationInputs(
        user_code=values["User Code"],
        subject_code=values["Subject Code"],
        bundle_no=values["Bundle No"],
        bundle_key=values["Bundle Key"],
    )


def deduplicate_sheet_numbers(labels: list[str]) -> list[str]:
    """Return unique six-digit sheet numbers in portal display order."""
    result: list[str] = []
    seen: set[str] = set()
    for label in labels:
        match = SHEET_NUMBER_PATTERN.fullmatch(label)
        if match and match.group(1) not in seen:
            seen.add(match.group(1))
            result.append(match.group(1))
    return result


def pdf_url_matches(url: str, subject_code: str, sheet_no: str) -> bool:
    """Check that a captured request is the requested sheet and subject PDF."""
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https":
        return False
    decoded_path = unquote(parsed.path)
    if not decoded_path.casefold().endswith(f"/{sheet_no}.pdf".casefold()):
        return False
    subject = subject_code.strip().casefold()
    path_parts = [part.casefold() for part in decoded_path.split("/") if part]
    return subject in path_parts


def _portal_error_text(page: Page) -> str | None:
    labels = page.locator("label").all_inner_texts()
    ignored = {"PROGRAM", "USER CODE", "BUNDLE NO", "BUNDLE KEY"}
    messages = [
        text.strip()
        for text in labels
        if text.strip() and text.strip().upper() not in ignored
    ]
    return messages[-1] if messages else None


def _wait_visible(page: Page, label: str, timeout_ms: int) -> None:
    try:
        page.get_by_label(label, exact=True).wait_for(
            state="visible", timeout=timeout_ms
        )
    except PlaywrightTimeoutError as exc:
        detail = _portal_error_text(page)
        suffix = f" Portal message: {detail}" if detail else ""
        raise PortalError(f"The portal did not open the {label} step.{suffix}") from exc


def _submit_step(
    page: Page, label: str, value: str, next_label: str, timeout_ms: int
) -> None:
    page.get_by_label(label, exact=True).fill(value)
    page.get_by_role(
        "button", name=re.compile(r"^\s*VALIDATE\s*$", re.IGNORECASE)
    ).click()
    _wait_visible(page, next_label, timeout_ms)


def _open_bundle(page: Page, inputs: EvaluationInputs, timeout_ms: int) -> None:
    try:
        page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=timeout_ms)
        page.get_by_role(
            "button", name=re.compile(r"FACULTY LOGIN", re.IGNORECASE)
        ).click()
        program = page.locator("select")
        program.wait_for(state="visible", timeout=timeout_ms)
        program.select_option(label="B.Tech")
        page.get_by_role(
            "button", name=re.compile(r"^\s*VALIDATE\s*$", re.IGNORECASE)
        ).click()
        _wait_visible(page, "USER CODE", timeout_ms)
        _submit_step(page, "USER CODE", inputs.user_code, "BUNDLE NO", timeout_ms)
        _submit_step(page, "BUNDLE NO", inputs.bundle_no, "BUNDLE KEY", timeout_ms)
        page.get_by_label("BUNDLE KEY", exact=True).fill(inputs.bundle_key)
        page.get_by_role(
            "button", name=re.compile(r"^\s*VALIDATE\s*$", re.IGNORECASE)
        ).click()
    except PortalError:
        raise
    except PlaywrightTimeoutError as exc:
        detail = _portal_error_text(page)
        suffix = f" Portal message: {detail}" if detail else ""
        raise PortalError(f"The HITAM portal timed out during login.{suffix}") from exc
    except PlaywrightError as exc:
        raise PortalError(f"The HITAM portal could not be opened: {exc}") from exc


def _sheet_numbers(page: Page, timeout_ms: int) -> list[str]:
    buttons = page.get_by_role("button", name=re.compile(r"^\s*\d{6}\s*$"))
    try:
        buttons.first.wait_for(state="visible", timeout=timeout_ms)
    except PlaywrightTimeoutError as exc:
        detail = _portal_error_text(page)
        suffix = f" Portal message: {detail}" if detail else ""
        raise PortalError(f"No student sheet numbers were returned.{suffix}") from exc

    numbers = deduplicate_sheet_numbers(buttons.all_inner_texts())
    if not numbers:
        raise PortalError("No six-digit student sheet numbers were found.")
    return numbers


def _capture_pdf_urls(
    page: Page,
    sheet_numbers: list[str],
    subject_code: str,
    timeout_ms: int,
) -> list[AnswerSheet]:
    answer_sheets: list[AnswerSheet] = []
    for sheet_no in sheet_numbers:
        button = page.get_by_role(
            "button", name=re.compile(rf"^\s*{re.escape(sheet_no)}\s*$")
        ).first
        try:
            with page.expect_request(
                lambda request, number=sheet_no: pdf_url_matches(
                    request.url, subject_code, number
                ),
                timeout=timeout_ms,
            ) as request_info:
                button.click()
            pdf_url = request_info.value.url
        except PlaywrightTimeoutError as exc:
            raise PortalError(
                f"No PDF request was observed for sheet {sheet_no}. "
                f"Confirm that Subject Code {subject_code!r} matches this bundle."
            ) from exc
        answer_sheets.append(AnswerSheet(sheet_no=sheet_no, pdf_url=pdf_url))
    return answer_sheets


def extract_from_page(
    page: Page,
    inputs: EvaluationInputs,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> list[AnswerSheet]:
    """Run the portal workflow in an existing page (also useful for tests)."""
    _open_bundle(page, inputs, timeout_ms)
    sheet_numbers = _sheet_numbers(page, timeout_ms)
    return _capture_pdf_urls(page, sheet_numbers, inputs.subject_code, timeout_ms)


def fetch_answer_sheets(
    inputs: EvaluationInputs,
    *,
    headless: bool = False,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> list[AnswerSheet]:
    """Launch Chromium, extract answer-sheet URLs, and always close the browser."""
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            try:
                page = browser.new_page()
                return extract_from_page(page, inputs, timeout_ms)
            finally:
                browser.close()
    except PortalError:
        raise
    except PlaywrightError as exc:
        message = str(exc)
        if "Executable doesn't exist" in message:
            raise PortalError(
                "Playwright Chromium is not installed. Run: playwright install chromium"
            ) from exc
        raise PortalError(f"Browser automation failed: {message}") from exc
