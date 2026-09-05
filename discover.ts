/**
 * discover.ts — One-time interactive setup for the Asah daily check-in script.
 *
 * What it does:
 *   1. Opens a HEADED browser (your installed Chrome/Edge) so you can log in
 *      to dicoding.com manually.
 *
 *      IMPORTANT: log in with EMAIL + PASSWORD on the Dicoding form.
 *      Do NOT click "Masuk dengan Google" — Google blocks OAuth in
 *      automation-driven browsers and will reject the sign-in. If your
 *      account is SSO-only, set a password first at
 *      https://www.dicoding.com/passwordreset (in your normal browser).
 *
 *      reCAPTCHA, if shown, is solved by you, not the script.
 *   2. Waits until you're logged in, then asks for / lets you navigate to the
 *      Asah check-in page.
 *   3. Scans the page for candidate "check-in" buttons, prints a numbered
 *      list, and asks you to pick the right one.
 *   4. Saves:
 *        - selector.json (page URL + selector strategies for checkin.ts)
 *      Session lives in your real Brave profile — nothing to export.
 *
 * Run:  npm run discover      (close all Brave windows first)
 */

import * as readline from "node:readline/promises";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "playwright";
import { launchBrave, firstPage } from "./browser";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const SELECTOR_PATH = path.join(__dirname, "selector.json");

const LOGIN_URL = "https://www.dicoding.com/login";

/** Words that hint at a check-in control (case-insensitive match on visible text). */
const CHECKIN_TEXT_HINTS = [
  "check-in",
  "checkin",
  "check in",
  "absen",
  "hadir",
  "presensi",
];

interface SelectorStrategy {
  /** Human-readable description */
  desc: string;
  /** Playwright selector expression */
  selector: string;
}

interface SavedConfig {
  /** Page the check-in control lives on */
  pageUrl: string;
  /** Ordered strategies; first match wins in checkin.ts */
  strategies: SelectorStrategy[];
  /** Visible text of the chosen element (for sanity check / already-done detection) */
  visibleText: string;
  savedAt: string;
}

function log(msg: string): void {
  console.log(`[discover] ${msg}`);
}

async function ask(rl: readline.Interface, question: string): Promise<string> {
  const answer = (await rl.question(question)).trim();
  return answer;
}

/** Returns true if the page shows signs of being logged in. */
function isLoggedIn(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const text = document.body?.innerText ?? "";
    // The logged-out site shows "Masuk" / "Daftar" CTAs in the navbar.
    const loggedOutMarkers = ["Masuk", "Daftar"];
    const hasLoggedOutMarker = loggedOutMarkers.some((m) =>
      new RegExp(`\\b${m}\\b`).test(text)
    );
    // A logged-in session generally exposes a profile/user menu; heuristics:
    const loggedInMarkers = ["Keluar", "Logout", "My Account", "Akun Saya", "Dashboard"];
    const hasLoggedInMarker = loggedInMarkers.some((m) =>
      new RegExp(`\\b${m}\\b`, "i").test(text)
    );
    return hasLoggedInMarker && !hasLoggedOutMarker;
  });
}

/**
 * Detects the "Google OAuth rejected inside automation browser" trap.
 * Google blocks OAuth in Playwright-driven browsers; landing on
 * accounts.google.com or a /rejected page means the user clicked the
 * Google button and must go back and use email+password instead.
 */
function isGoogleTrap(url: string): boolean {
  try {
    const u = new URL(url);
    return (
      u.hostname === "accounts.google.com" ||
      u.hostname.endsWith(".accounts.google.com") ||
      /\/rejected/i.test(u.pathname) ||
      u.searchParams.has("oauth_error") // generic fallback
    );
  } catch {
    return false;
  }
}

/** Attempts to leave the trap by going back to the Dicoding login page. */
async function escapeGoogleTrap(page: Page): Promise<void> {
  console.log("");
  console.log("  ============================================================");
  console.log("  GOOGLE LOGIN TRAP DETECTED");
  console.log("  Google blocks OAuth inside automation browsers - this is");
  console.log("  expected and NOT fixable by retrying.");
  console.log("");
  console.log("  DO THIS: log in with EMAIL + PASSWORD on the Dicoding form.");
  console.log("  (SSO-only account? Set a password first at");
  console.log("   https://www.dicoding.com/passwordreset in your normal browser.)");
  console.log("  Navigating back to the Dicoding login page...");
  console.log("  ============================================================");
  console.log("");
  await page.goto(LOGIN_URL, { waitUntil: "domcontentloaded" }).catch(() => {});
}

/**
 * Collects candidate clickable elements whose visible text matches check-in hints.
 * Includes elements inside same-origin iframes.
 */
async function findCandidates(page: Page): Promise<
  Array<{
    idx: number;
    text: string;
    tag: string;
    inIframe: boolean;
    rect: { x: number; y: number; w: number; h: number };
  }>
> {
  const results: Array<{
    idx: number;
    text: string;
    tag: string;
    inIframe: boolean;
    rect: { x: number; y: number; w: number; h: number };
  }> = [];

  const scanFrame = async (frame: import("playwright").Frame, inIframe: boolean) => {
    let found: Array<{
      text: string;
      tag: string;
      rect: { x: number; y: number; w: number; h: number };
    }> = [];
    try {
      found = await frame.evaluate((hints: string[]) => {
        const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const patterns = hints.map(
          (h) => new RegExp(escapeRe(h).replace(/\\?\s+/g, "\\s+"), "i")
        );
        const out: Array<{
          text: string;
          tag: string;
          rect: { x: number; y: number; w: number; h: number };
        }> = [];

        const clickables = Array.from(
          document.querySelectorAll(
            'button, a, [role="button"], input[type="button"], input[type="submit"], div[onclick], [class*="checkin" i], [class*="check-in" i], [id*="checkin" i], [id*="check-in" i]'
          )
        );
        for (const el of clickables) {
          const style = window.getComputedStyle(el);
          if (
            style.display === "none" ||
            style.visibility === "hidden" ||
            parseFloat(style.opacity) < 0.1
          ) {
            continue;
          }
          const text = (el.textContent ?? "").replace(/\s+/g, " ").trim();
          const isMatch =
            patterns.some((p) => p.test(text)) ||
            patterns.some((p) => p.test(el.className?.toString?.() ?? "")) ||
            patterns.some((p) => p.test(el.id ?? ""));
          if (!isMatch || text.length > 120) continue;
          const r = el.getBoundingClientRect();
          if (r.width === 0 && r.height === 0) continue;
          out.push({
            text,
            tag: el.tagName.toLowerCase(),
            rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
          });
        }
        // Deduplicate by text+position
        const seen = new Set<string>();
        return out.filter((c) => {
          const key = `${c.text}|${c.rect.x}|${c.rect.y}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        });
      }, CHECKIN_TEXT_HINTS);
    } catch {
      // Frame may be cross-origin or navigated away; skip it.
      return;
    }

    for (const f of found) {
      results.push({ ...f, inIframe, idx: 0 });
    }
  };

  await scanFrame(page.mainFrame(), false);
  for (const frame of page.frames()) {
    if (frame !== page.mainFrame()) await scanFrame(frame, true);
  }

  results.forEach((r, i) => (r.idx = i + 1));
  return results;
}

/** Builds ordered selector strategies for a chosen candidate. */
async function buildStrategies(
  page: Page,
  chosen: { text: string; tag: string; inIframe: boolean; rect: { x: number; y: number; w: number; h: number } }
): Promise<SelectorStrategy[]> {
  const strategies: SelectorStrategy[] = [];

  if (chosen.inIframe) {
    // Iframe-only strategies (checkin.ts handles frame lookup separately).
    strategies.push({
      desc: "text match in any frame",
      selector: `text=${chosen.text.slice(0, 60)}`,
    });
    strategies.push({
      desc: "visible text regex match in any frame",
      selector: `:is(button, a, [role="button"]):has-text("${chosen.text.slice(0, 60)}")`,
    });
    return strategies;
  }

  // Strategy 1: exact visible text on a role-ish element (most stable across re-renders)
  const escapedText = chosen.text.replace(/"/g, '\\"');
  strategies.push({
    desc: "button/link with exact text",
    selector: `:is(button, a, [role="button"]):has-text("${escapedText}")`,
  });

  // Strategy 2: any element with that text
  strategies.push({
    desc: "any element with text",
    selector: `text=${chosen.text.slice(0, 60)}`,
  });

  // Strategy 3: data attributes captured from the element itself
  const dataAttrs = await page.evaluate((rect) => {
    const els = Array.from(document.querySelectorAll<HTMLElement>("*"));
    const hit = els.find((el) => {
      const r = el.getBoundingClientRect();
      return (
        Math.abs(r.x - rect.x) < 3 &&
        Math.abs(r.y - rect.y) < 3 &&
        Math.abs(r.width - rect.w) < 3 &&
        Math.abs(r.height - rect.h) < 3
      );
    });
    if (!hit) return null;
    const attrs: Record<string, string> = {};
    for (const attr of Array.from(hit.attributes)) {
      if (attr.name.startsWith("data-") && attr.value) attrs[attr.name] = attr.value;
    }
    return { tag: hit.tagName.toLowerCase(), id: hit.id, attrs };
  }, chosen.rect);

  if (dataAttrs?.id) {
    strategies.push({
      desc: "element id",
      selector: `#${dataAttrs.id}`,
    });
  }
  if (dataAttrs) {
    for (const [name, value] of Object.entries(dataAttrs.attrs)) {
      strategies.push({
        desc: `attribute ${name}="${value}"`,
        selector: `[${name}="${value}"]`,
      });
    }
  }
  if (dataAttrs?.tag && dataAttrs.tag !== chosen.tag) {
    strategies.push({
      desc: `outer <${dataAttrs.tag}> with text`,
      selector: `${dataAttrs.tag}:has-text("${escapedText}")`,
    });
  }

  return strategies;
}

async function main(): Promise<void> {
  log("Starting interactive discovery...");
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

  log("Launching REAL Brave profile (close all Brave windows first)...");
  const context = await launchBrave();
  const page = firstPage(context);

  // Step 1 — login
  await page.goto(LOGIN_URL, { waitUntil: "domcontentloaded" });
  log("Browser opened on Dicoding login. If already logged in, login check passes shortly.");
  log("If not: log in however you like (Google button should work — real profile).");
  log("Waiting for logged-in state (polling, up to 10 minutes)...");
  const loginDeadline = Date.now() + 10 * 60 * 1000;
  let loggedIn = false;
  let lastFeedback = Date.now();
  while (Date.now() < loginDeadline) {
    // Trap check first — fast feedback beats dead waiting.
    if (isGoogleTrap(page.url())) {
      await escapeGoogleTrap(page);
      lastFeedback = Date.now();
      continue;
    }
    try {
      loggedIn = await isLoggedIn(page);
    } catch {
      loggedIn = false;
    }
    if (loggedIn) break;

    // Heartbeat so silence never looks like a hang.
    if (Date.now() - lastFeedback > 15000) {
      log(`Still waiting... current page: ${page.url()}`);
      lastFeedback = Date.now();
    }
    await page.waitForTimeout(2000);
  }
  if (!loggedIn) {
    console.error("[discover] Timed out waiting for login. Exiting.");
    await context.close();
    process.exit(1);
  }
  log("Looks like you're logged in!");

  // Step 2 — navigate to check-in page
  let targetUrl = await ask(
    rl,
    "\nPaste the URL of the Asah check-in page (or press Enter if you've already navigated there): "
  );
  if (targetUrl) {
    if (!/^https?:\/\//i.test(targetUrl)) targetUrl = `https://${targetUrl}`;
    log(`Navigating to ${targetUrl} ...`);
    await page.goto(targetUrl, { waitUntil: "domcontentloaded" });
  } else {
    log("Assuming you've already navigated to the check-in page in the browser.");
  }
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  log(`Current URL: ${page.url()}`);

  // Step 3 — scan for candidates
  log("Scanning for check-in-ish clickable elements...");
  const candidates = await findCandidates(page);
  if (candidates.length === 0) {
    console.error(
      "[discover] No candidates found. Make sure the check-in button is visible on the page, then re-run."
    );
    await context.close();
    process.exit(1);
  }
  console.log("\nFound candidates:");
  for (const c of candidates) {
    console.log(
      `  ${c.idx}. [${c.inIframe ? "iframe, " : ""}<${c.tag}>] "${c.text}" @ (${c.rect.x},${c.rect.y}) ${c.rect.w}x${c.rect.h}`
    );
  }

  const choiceStr = await ask(rl, "\nWhich number is the check-in button? (Enter to re-scan / Ctrl+C to abort): ");
  const choice = parseInt(choiceStr, 10);
  const chosen = candidates.find((c) => c.idx === choice);
  if (!chosen) {
    console.error("[discover] Invalid choice. Exiting — re-run `npm run discover` to try again.");
    await context.close();
    process.exit(1);
  }

  // Step 4 — build + save selector strategies
  const strategies = await buildStrategies(page, chosen);
  const config: SavedConfig = {
    pageUrl: page.url(),
    strategies,
    visibleText: chosen.text,
    savedAt: new Date().toISOString(),
  };
  fs.writeFileSync(SELECTOR_PATH, JSON.stringify(config, null, 2), "utf-8");
  log(`Saved selector config -> ${SELECTOR_PATH}`);

  // Session lives in the real Brave profile — nothing to save here.

  // Optional: test the primary strategy right now
  const testNow = await ask(rl, "\nTest the primary selector now (clicks the button for real!)? [y/N]: ");
  if (testNow.toLowerCase() === "y") {
    log("Testing primary strategy by clicking...");
    try {
      const el = page.locator(strategies[0].selector).first();
      await el.click({ timeout: 5000 });
      log("Clicked! Check the browser for what happened (toast/modal/etc.), then press Enter here.");
      await rl.question("Describe what you saw (free text, saved to notes): ");
    } catch (e) {
      log(`Primary selector test failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  } else {
    log("Skipping live click test. You can test via `npm run checkin`.");
  }

  console.log("\n=== Discovery complete ===");
  console.log("Next step: run `npm run checkin` whenever you want to check in.");
  await context.close();
  rl.close();
}

main().catch((err) => {
  console.error("[discover] Fatal error:", err);
  process.exit(1);
});
