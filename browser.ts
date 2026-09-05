/**
 * browser.ts — launches the user's REAL Brave profile, headed.
 * The profile carries the session, so no storage-state files are needed.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { chromium, type BrowserContext } from "playwright";

// ponytail: single hardcoded target (user-confirmed install). Upgrade path:
// turn into resolved list + CLI flag if a second browser ever matters.
const BRAVE_EXE = "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe";
const BRAVE_PROFILE = path.join(process.env.LOCALAPPDATA ?? "", "BraveSoftware", "Brave-Browser", "User Data");

export async function launchBrave(): Promise<BrowserContext> {
  if (!fs.existsSync(BRAVE_EXE)) {
    throw new Error(`Brave not found at ${BRAVE_EXE}. Install it or edit BRAVE_EXE in browser.ts.`);
  }
  try {
    return await chromium.launchPersistentContext(BRAVE_PROFILE, {
      executablePath: BRAVE_EXE,
      headless: false, // always headed, per user request
      viewport: null, // real window size
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (/singleton|lock|already|ProcessSingleton/i.test(msg)) {
      throw new Error(
        "Brave appears to be running. Close ALL Brave windows (check the system tray too), then run again.\n" +
          "Raw error: " + msg.split("\n")[0]
      );
    }
    throw e;
  }
}

/** Reuses the blank tab a persistent context opens with, if any. */
export function firstPage(context: BrowserContext) {
  return context.pages()[0] ?? context.newPage();
}
