/**
 * checkin.ts — Daily check-in runner for the Dicoding Asah program.
 *
 * Preconditions (created by `npm run discover`):
 *   - selector.json : page URL + selector strategies for the check-in button
 *   - logged-in session lives in your real Brave profile
 *
 * Behavior:
 *   1. Launches your real Brave profile (headed — window is always visible).
 *   2. Goes to the saved check-in page URL.
 *   3. If already checked in, logs it and exits. Otherwise clicks the button
 *      via the first matching strategy.
 *   4. Saves a dated screenshot + appends a line to runs/checkin.log.
 *
 * Safety: it only ever clicks the selector confirmed during discovery.
 * It never touches other interactive elements.
 *
 * Usage:
 *   npm run checkin     (close all Brave windows first)
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { Locator, Page } from "playwright";
import { launchBrave, firstPage } from "./browser";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const SELECTOR_PATH = path.join(__dirname, "selector.json");
const RUNS_DIR = path.join(__dirname, "runs");
const LOG_PATH = path.join(RUNS_DIR, "checkin.log");

interface SelectorStrategy {
  desc: string;
  selector: string;
}

interface SavedConfig {
  pageUrl: string;
  strategies: SelectorStrategy[];
  visibleText: string;
  savedAt: string;
}

function timestamp(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

function log(msg: string): void {
  console.log(`[checkin] ${msg}`);
}

async function appendRunLog(line: string): Promise<void> {
  fs.mkdirSync(RUNS_DIR, { recursive: true });
  fs.appendFileSync(LOG_PATH, `[${new Date().toISOString()}] ${line}\n`, "utf-8");
}

async function saveScreenshot(page: Page, label: string): Promise<string> {
  fs.mkdirSync(RUNS_DIR, { recursive: true });
  const file = path.join(RUNS_DIR, `${timestamp()}_${label}.png`);
  await page.screenshot({ path: file, fullPage: true }).catch(() => {});
  return file;
}

/** Heuristic: does the page currently indicate "already checked in today"? */
async function looksAlreadyCheckedIn(page: Page): Promise<boolean> {
  return page
    .evaluate(() => {
      const text = (document.body?.innerText ?? "").toLowerCase();
      const doneMarkers = [
        "already checked in",
        "sudah check-in",
        "sudah absen",
        "sudah melakukan check-in",
        "checked in today",
        "see you tomorrow",
        "sampai jumpa besok",
      ];
      return doneMarkers.some((m) => text.includes(m));
    })
    .catch(() => false);
}

async function findButton(page: Page, strategies: SelectorStrategy[]): Promise<Locator | null> {
  for (const strat of strategies) {
    try {
      const loc = page.locator(strat.selector).first();
      await loc.waitFor({ state: "visible", timeout: 3000 });
      log(`Button found via strategy: ${strat.desc}`);
      return loc;
    } catch {
      log(`Strategy missed: ${strat.desc}`);
    }
  }
  return null;
}

async function main(): Promise<void> {
  if (!fs.existsSync(SELECTOR_PATH)) {
    console.error(
      "[checkin] selector.json not found. Run `npm run discover` first to pick the check-in button."
    );
    process.exit(1);
  }

  const config: SavedConfig = JSON.parse(fs.readFileSync(SELECTOR_PATH, "utf-8"));
  log(`Loaded config saved at ${config.savedAt} for URL: ${config.pageUrl}`);

  log("Launching real Brave profile (headed). Close all Brave windows before running.");
  const context = await launchBrave();
  const page = firstPage(context);

  let outcome = "unknown";
  let detail = "";

  try {
    await page.goto(config.pageUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
    log(`Landed on: ${page.url()}`);

    // Session-expiry check: if we got bounced back to a login page, bail out clearly.
    if (/\/login(\?|$)/.test(new URL(page.url()).pathname)) {
      outcome = "session-expired";
      detail = "Redirected to login. Run `npm run discover` to log in again (session lives in Brave profile).";
      log(detail);
      await saveScreenshot(page, "session_expired");
      process.exitCode = 2;
      return;
    }

    // Already checked in?
    if (await looksAlreadyCheckedIn(page)) {
      outcome = "already-checked-in";
      detail = "Page reports already checked in today — nothing to do.";
      log(detail);
      await saveScreenshot(page, "already_checked_in");
      process.exitCode = 0;
      return;
    }

    // Find the button
    const button = await findButton(page, config.strategies);
    if (!button) {
      outcome = "button-not-found";
      detail = "No selector strategy matched. Page layout may have changed — re-run `npm run discover`.";
      log(detail);
      await saveScreenshot(page, "button_not_found");
      process.exitCode = 3;
      return;
    }

    // Click once, wait for network to settle
    log("Clicking check-in button...");
    await button.click({ timeout: 5000 });
    await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(1500); // let toasts/modals appear

    const shotAfter = await saveScreenshot(page, "after_click");

    // Post-click verification (best-effort, page-specific)
    const stillThere = await button.isVisible().catch(() => false);
    const alreadyDoneNow = await looksAlreadyCheckedIn(page);

    if (alreadyDoneNow || !stillThere) {
      outcome = "clicked-verified";
      detail = "Clicked; success signals detected (button gone / already-checked-in text appeared).";
    } else {
      outcome = "clicked-unverified";
      detail = "Clicked, but success signals not detected. Verify manually via screenshot.";
      process.exitCode = 1;
    }
    log(detail);
    log(`Screenshot: ${shotAfter}`);
  } catch (err) {
    outcome = "error";
    detail = err instanceof Error ? err.message : String(err);
    log(`Error: ${detail}`);
    await saveScreenshot(page, "error").catch(() => {});
    process.exitCode = 4;
  } finally {
    await appendRunLog(`${outcome} | ${detail}`);
    // ponytail: closes the whole real Brave window set, not just our tab —
    // acceptable because the run contract is "Brave closed before running".
    // Upgrade path: track our own tabs and close only those.
    await context.close().catch(() => {});
  }
}

main().catch((err) => {
  console.error("[checkin] Fatal error:", err);
  process.exit(1);
});
