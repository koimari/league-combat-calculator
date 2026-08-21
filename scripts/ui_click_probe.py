"""Drive the running page through the setup workflows and count the clicks.

The evidence behind docs/plans/2026-08-20-ui-audit-and-click-pass.md: each
workflow is performed on the real page (Playwright, headless Chromium) and
the click count, the numbers the verdict shows, and any page error are
printed. Run against a local server::

    python -m flask --app src.app --debug run --no-reload
    python scripts/ui_click_probe.py [http://127.0.0.1:5000/]
"""

from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

NL = chr(10)


def main(url: str) -> int:
    clicks: list[str] = []
    errors: list[str] = []

    def click(page, selector, label):
        page.locator(selector).locator("visible=true").first.click()
        clicks.append(label)
        page.wait_for_timeout(150)

    def settle(page):
        page.wait_for_function(
            "() => document.getElementById('resultStatus')"
            ".textContent.indexOf('calculating') < 0",
            timeout=60000,
        )
        page.wait_for_timeout(400)

    def text(page, selector, limit=400):
        return page.locator(selector).inner_text()[:limit].replace(NL, " | ")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        page.wait_for_timeout(2500)
        if page.locator("#onboardingOverlay.is-open").count():
            click(page, ".onboarding-skip", "onboarding skip")

        # Champion to level 18: open, pick, one breakpoint.
        start = len(clicks)
        click(page, '[data-step-toggle="champion"]', "open step 1")
        page.fill("#pickerSearch", "Aatrox")
        click(page, '[data-picker-value="Aatrox"]', "pick Aatrox")
        click(page, '[data-level-set="attacker.level"][data-value="18"]', "level 18")
        print(
            "champion -> LV 18:",
            len(clicks) - start,
            "clicks; level",
            page.locator("#levelOutput").inner_text(),
        )
        print("ability cards:", text(page, "#abilityRow", 300))
        click(page, '[data-step-toggle="none"]', "done")

        # Enemy inherits the level; the dummy is the one-click target.
        start = len(clicks)
        click(page, '[data-step-toggle="roster"]', "open roster")
        click(page, "#addEnemy", "add enemy")
        page.fill("#pickerSearch", "Akali")
        click(page, '[data-picker-value="Akali"]', "pick Akali")
        print(
            "enemy at:",
            page.locator("#enemies output").first.inner_text(),
            "in",
            len(clicks) - start,
            "clicks",
        )
        click(page, '[data-roster-level-all="11"]', "everyone 11")
        print("everyone -> 11:", page.locator("#enemies output").first.inner_text())
        click(page, '[data-step-toggle="none"]', "done")
        settle(page)
        print(
            "verdict:",
            page.locator("#scoreA").inner_text(),
            "|",
            page.locator("#verdictNoteA").inner_text(),
        )

        # Five ordinary items (boots on): one open, five picks.
        start = len(clicks)
        click(
            page, '[data-picker="item"][data-path="attacker.buildA.0"]', "open slot 1"
        )
        for name in ["Eclipse", "Black Cleaver", "Sterak", "Spirit Visage", "Sundered"]:
            page.fill("#pickerSearch", name)
            page.wait_for_timeout(80)
            click(page, "#pickerGrid .picker-option:not([disabled])", f"pick {name}")
        print(
            "five items:",
            len(clicks) - start,
            "clicks; picker open:",
            bool(page.locator("#picker[open]").count()),
        )
        settle(page)

        # The whole rune page in one dialog.
        start = len(clicks)
        click(page, '[data-rune-page="A"]', "open rune page")
        click(
            page, '[data-rune-pick="keystone"][data-rune-name="Conqueror"]', "Conqueror"
        )
        groups = lambda: page.locator("#runePageBody .rune-group")  # noqa: E731
        for row in range(3):
            groups().nth(1).locator(".rune-row").nth(row).locator(
                ".rune-pick:not([disabled])"
            ).first.click()
            clicks.append(f"primary row {row + 1}")
            page.wait_for_timeout(100)
        for row in (0, 2):
            groups().nth(2).locator(".rune-path").nth(1).locator(".rune-row").nth(
                row
            ).locator(".rune-pick:not([disabled])").first.click()
            clicks.append(f"secondary row {row + 1}")
            page.wait_for_timeout(100)
        for row in range(3):
            groups().nth(3).locator(".rune-row").nth(row).locator(
                ".rune-pick:not([disabled])"
            ).first.click()
            clicks.append(f"shard {row + 1}")
            page.wait_for_timeout(100)
        print(
            "rune page:",
            len(clicks) - start,
            "clicks;",
            page.locator("#runePageKicker").inner_text(),
        )
        click(page, "#runePageClose", "close rune page")
        settle(page)
        print(
            "verdict with runes:",
            page.locator("#scoreA").inner_text(),
            "|",
            page.locator("#verdictNoteA").inner_text(),
            "| error:",
            page.locator("#engineError").inner_text() or "none",
        )

        # Autos only.
        click(page, '[data-constraint-toggle="window"]', "open window")
        click(page, '[data-fight-mode="autos"]', "autos only")
        settle(page)
        print(
            "autos only:",
            page.locator("#scoreA").inner_text(),
            "|",
            page.locator("#verdictNoteA").inner_text(),
            "|",
            page.locator("#windowValue").inner_text(),
        )

        page.locator("#ledgerBand > summary.ledger-summary").click()
        page.wait_for_timeout(300)
        print("event lanes:", text(page, "#timeline", 500))
        print("page errors:", errors or "none")
        print("clicks:", len(clicks), json.dumps(clicks))
        browser.close()
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000/"))
