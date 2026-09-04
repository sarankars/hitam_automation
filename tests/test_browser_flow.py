from __future__ import annotations

import os
from unittest import TestCase, skipUnless

from playwright.sync_api import sync_playwright

from hitam_cli.portal import EvaluationInputs, extract_from_page


@skipUnless(
    os.getenv("HITAM_RUN_BROWSER_TESTS") == "1", "browser integration test is opt-in"
)
class MockBrowserFlowTests(TestCase):
    def test_mocked_portal_flow_captures_actual_pdf_requests(self):
        html = """
        <button id="faculty">FACULTY LOGIN</button>
        <div id="stage"></div>
        <script>
        const stage = document.querySelector('#stage');
        const field = label => `<label>${label}<input aria-label="${label}"></label><button>VALIDATE</button>`;
        document.querySelector('#faculty').onclick = () => {
          stage.innerHTML = '<select><option>B.Tech</option></select><button>VALIDATE</button>';
          stage.querySelector('button').onclick = () => { stage.innerHTML = field('USER CODE'); wire('BUNDLE NO'); };
        };
        function wire(next) {
          stage.querySelector('button').onclick = () => {
            if (next === 'BUNDLE NO') { stage.innerHTML = field(next); wire('BUNDLE KEY'); }
            else if (next === 'BUNDLE KEY') { stage.innerHTML = field(next); wire('SHEETS'); }
            else {
              stage.innerHTML = '<button>000001</button><button>123456</button><button>123456</button>';
              for (const button of stage.querySelectorAll('button')) {
                button.onclick = () => fetch(`https://mock.local/ScriptPDF/CS101/${button.textContent}.pdf`);
              }
            }
          };
        }
        </script>
        """
        inputs = EvaluationInputs("USER", "CS101", "BUNDLE", "KEY")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.route(
                    "https://hitamexams.org/MidEvaluation/",
                    lambda route: route.fulfill(body=html),
                )
                page.route(
                    "https://mock.local/**",
                    lambda route: route.fulfill(body="%PDF-mock"),
                )
                rows = extract_from_page(page, inputs, timeout_ms=5_000)
            finally:
                browser.close()

        self.assertEqual([row.sheet_no for row in rows], ["000001", "123456"])
        self.assertTrue(rows[0].pdf_url.endswith("/CS101/000001.pdf"))
