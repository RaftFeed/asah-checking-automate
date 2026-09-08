#!/usr/bin/env python3
"""Daily check-in for Dicoding Asah. Headed isolated Chrome profile (no headless => no headless flags).

Usage:
  .venv\\Scripts\\python checkin.py            # run check-in (main Chrome can stay open)
  .venv\\Scripts\\python checkin.py --force    # bypass today-already-done guard
  .venv\\Scripts\\python checkin.py --discover # one-time setup: login, pick button, save selector.json
  .venv\\Scripts\\python checkin.py --selftest # assert pick_daily rotation, no browser needed

Skips browser when runs/last-success.txt holds today. Guard resets daily by date compare.
Or double-click checkin.bat (same as run, pauses so window stays open).

Reuses selector.json, form-answers.json, runs/ log format from the TS version.
"""
import argparse
import datetime
import json
import os
import pathlib
import random
import re
import sys
import time

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).parent
SELECTOR_PATH = HERE / "selector.json"
ANSWERS_PATH = HERE / "form-answers.json"
RUNS_DIR = HERE / "runs"
LOG_PATH = RUNS_DIR / "checkin.log"
LAST_OK_PATH = RUNS_DIR / "last-success.txt"
LAST_REFLECTION_PATH = RUNS_DIR / "last-reflection.txt"
LOGIN_URL = "https://www.dicoding.com/login"

WIB = datetime.timezone(datetime.timedelta(hours=7))


def now_wib():
    return datetime.datetime.now(WIB)


def load_dotenv():
    env_path = HERE / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
        except Exception:
            pass


load_dotenv()


def get_chrome_path():
    if custom := os.environ.get("CHROME_PATH"):
        return custom
    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return candidates[0]
    if sys.platform == "darwin":
        mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        return mac if os.path.exists(mac) else "google-chrome"
    return "google-chrome"


# ponytail: isolated automation profile so main Chrome can stay open. Login persists here after first --discover.
CHROME_EXE = get_chrome_path()
CHROME_PROFILE = str(HERE / ".chrome-profile")

CHECKIN_TEXT_HINTS = ["check-in", "checkin", "check in", "absen", "hadir", "presensi"]
BUILTIN_DONE_MARKERS = [
    "already checked in", "sudah check-in", "sudah absen", "sudah melakukan check-in",
    "checked in today", "see you tomorrow", "sampai jumpa besok",
]
SUBMIT_CANDIDATES = [
    '#checkinForm button[type="submit"]', '#checkinSubmit',
    'form button[type="submit"]', 'form input[type="submit"]',
    'button:has-text("Kirim")', 'button:has-text("Submit")', 'button:has-text("Simpan")',
    'button:has-text("Check-in")', 'button:has-text("Check in")',
]


def log(msg, tag="checkin"):
    try:
        print(f"[{tag}] {msg}", flush=True)
    except UnicodeEncodeError:
        # ponytail: cp1252 console can't take emoji (mood labels). Degrade, don't abort the run.
        print(f"[{tag}] " + str(msg).encode("ascii", "replace").decode(), flush=True)


def timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")


def append_run_log(line):
    RUNS_DIR.mkdir(exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] {line}\n")


def today_str():
    return now_wib().date().isoformat()


def read_last_success():
    try:
        return LAST_OK_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def write_last_success():
    RUNS_DIR.mkdir(exist_ok=True)
    LAST_OK_PATH.write_text(today_str() + "\n", encoding="utf-8")


def is_done_today():
    return read_last_success() == today_str()


def save_screenshot(page, label):
    RUNS_DIR.mkdir(exist_ok=True)
    file = RUNS_DIR / f"{timestamp()}_{label}.png"
    try:
        page.screenshot(path=str(file), full_page=True)
    except Exception:
        pass
    return str(file)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def preflight_check():
    if not SELECTOR_PATH.exists():
        return False, "selector.json not found. Run `python checkin.py --discover` first."
    config = read_json(SELECTOR_PATH)
    if not config or not config.get("pageUrl") or not config.get("strategies"):
        return False, "selector.json invalid or missing pageUrl/strategies. Run `python checkin.py --discover` first."
    if ANSWERS_PATH.exists():
        try:
            content = ANSWERS_PATH.read_text(encoding="utf-8")
            json.loads(content)
        except Exception as e:
            return False, f"form-answers.json syntax error: {e}"
    return True, ""


def notify_failure(message="Dicoding check-in failed!"):
    if sys.platform == "win32":
        try:
            import subprocess
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", "[System.Media.SystemSounds]::Hand.Play()"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            pass


def get_done_markers():
    custom = (read_json(SELECTOR_PATH, {}) or {}).get("doneMarkers", [])
    seen = set(BUILTIN_DONE_MARKERS)
    out = list(BUILTIN_DONE_MARKERS)
    for m in custom if isinstance(custom, list) else []:
        m = str(m).lower()
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def add_custom_done_markers(markers):
    cfg = read_json(SELECTOR_PATH, {}) or {}
    prev = cfg.get("doneMarkers", []) if isinstance(cfg.get("doneMarkers"), list) else []
    merged = list(dict.fromkeys([str(m).lower() for m in prev + markers]))
    cfg["doneMarkers"] = merged
    SELECTOR_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def looks_already_checked_in(page):
    try:
        return bool(page.evaluate(
            "(ms) => (document.body?.innerText ?? '').replace(/\\s+/g, ' ').toLowerCase().split('').length >= 0 && ms.some((m) => (document.body?.innerText ?? '').replace(/\\s+/g, ' ').toLowerCase().includes(m))",
            get_done_markers()))
    except Exception:
        return False


def dump_page_text(page, label):
    RUNS_DIR.mkdir(exist_ok=True)
    file = RUNS_DIR / f"{label}_page.txt"
    try:
        text = page.evaluate("() => (document.body?.innerText ?? '').replace(/\\s+/g, ' ').trim()")
    except Exception:
        text = "(could not read page text)"
    file.write_text(text or "", encoding="utf-8")
    return str(file)


def launch_chrome(p):
    if not os.path.exists(CHROME_EXE):
        raise RuntimeError(f"Chrome not found at '{CHROME_EXE}'. Set CHROME_PATH environment variable or install Google Chrome.")
    try:
        os.makedirs(CHROME_PROFILE, exist_ok=True)
        return p.chromium.launch_persistent_context(
            CHROME_PROFILE, executable_path=CHROME_EXE, headless=False, no_viewport=True,
            args=["--no-first-run", "--no-default-browser-check"])
    except Exception as e:
        msg = str(e).split("\n")[0]
        if re.search(r"singleton|lock|already|ProcessSingleton", msg, re.I):
            raise RuntimeError("Automation Chrome profile locked. Close the automation window / kill leftover chrome, then run again.\nRaw: " + msg)
        raise


def first_page(context):
    return context.pages[0] if context.pages else context.new_page()


def find_button(page, strategies):
    for s in strategies:
        try:
            loc = page.locator(s["selector"]).first
            loc.wait_for(state="visible", timeout=3000)
            log(f"Button found via strategy: {s.get('desc', s['selector'])}")
            return loc
        except Exception:
            log(f"Strategy missed: {s.get('desc', s['selector'])}")
    return None


def pick_daily(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        if not value:
            return ""
        return value[(now_wib().day - 1) % len(value)]
    if isinstance(value, dict):
        pool = value.get("weekend" if now_wib().weekday() >= 5 else "weekday") or []
        if not pool:
            return ""
        last_pick = ""
        try:
            if LAST_REFLECTION_PATH.exists():
                last_pick = LAST_REFLECTION_PATH.read_text(encoding="utf-8").strip()
        except Exception:
            pass
        choice = random.choice(pool)
        if len(pool) > 1 and choice == last_pick:
            choice = random.choice([p for p in pool if p != last_pick] or pool)
        try:
            RUNS_DIR.mkdir(exist_ok=True)
            LAST_REFLECTION_PATH.write_text(choice, encoding="utf-8")
        except Exception:
            pass
        return choice
    return ""


# ponytail: scoped to open modal when one exists (dashboard has 2000+ hidden inputs).
# Radio/checkbox count when their label face is visible — real inputs are often custom-styled to 0px.
def enumerate_form(page):
    try:
        return page.evaluate("""() => {
          const labelFor = (el) => {
            if (el.id) { const l = document.querySelector(`label[for="${el.id}"]`);
              if (l?.textContent) return l.textContent.replace(/\\s+/g, ' ').trim(); }
            const c = el.closest('label');
            if (c?.textContent) return c.textContent.replace(/\\s+/g, ' ').trim();
            const w = el.closest('.form-group, .field, div');
            const l2 = w?.querySelector('label');
            if (l2?.textContent) return l2.textContent.replace(/\\s+/g, ' ').trim();
            return el.getAttribute('aria-label') ?? el.getAttribute('placeholder') ?? el.getAttribute('name') ?? '';
          };
          const vis = (el) => { if (!el) return false; const s = window.getComputedStyle(el); const r = el.getBoundingClientRect();
            return !el.hasAttribute('hidden') && el.getAttribute('aria-hidden') !== 'true' &&
              s.display !== 'none' && s.visibility !== 'hidden' && parseFloat(s.opacity || '1') > 0 && r.width > 0 && r.height > 0; };
          const shown = (el) => vis(el) || vis(el.closest('label'));
          const root = document.querySelector('div.modal.show') || document;
          const out = []; const seen = new Set();
          for (const el of root.querySelectorAll('input, textarea, select')) {
            const tag = el.tagName.toLowerCase(); const type = (el.type || '').toLowerCase();
            if (['hidden','submit','button'].includes(type)) continue;
            const isCheck = type === 'radio' || type === 'checkbox';
            if (isCheck ? !shown(el) : !vis(el)) continue;
            const name = el.getAttribute('name') ?? el.id ?? '';
            if (!name) continue;
            if (type === 'radio') { if (seen.has(name)) continue; seen.add(name);
              const opts = [...root.querySelectorAll(`input[type="radio"][name="${name}"]`)].filter(shown).map(labelFor).filter(Boolean);
              out.push({kind:'radio-group', name, label:labelFor(el) || name, options:opts});
            } else if (type === 'checkbox') out.push({kind:'checkbox', name, label:labelFor(el) || name});
            else if (tag === 'select') out.push({kind:'select', name, label:labelFor(el) || name,
              options:[...el.options].map((o) => (o.textContent || '').trim())});
            else out.push({kind: tag === 'textarea' ? 'textarea' : 'input', name, label:labelFor(el) || name});
          }
          return out;
        }""") or []
    except Exception:
        return []


def fill_form(page, fields, answers):
    filled = 0
    for f in fields:
        key = f["label"] if answers.get(f["label"]) is not None else (f["name"] if answers.get(f["name"]) is not None else None)
        if key is None:
            # ponytail: unchecked checkbox is a valid answer (materi not done). Uncheck to be explicit, count it.
            if f["kind"] == "checkbox":
                try:
                    page.locator(f'input[type="checkbox"][name="{f["name"]}"]').first.uncheck(timeout=3000, force=True)
                except Exception:
                    pass
                filled += 1
                continue
            log(f'no answer for field "{f.get("label") or f.get("name")}" ({f["kind"]}) — skipped', "form")
            continue
        val = answers[key]
        try:
            if f["kind"] == "radio-group" and f.get("options"):
                opts = [str(o).lower() for o in f["options"]]
                try:
                    idx = opts.index(val.lower())
                except ValueError:
                    idx = next((i for i, o in enumerate(opts) if val.lower() in o), 0)
                # ponytail: JS click on label — real radios are custom-styled to 0px, force check still fails.
                ok = page.evaluate("""({name, idx}) => {
                  const root = document.querySelector('div.modal.show') || document;
                  const radios = [...root.querySelectorAll(`input[type="radio"][name="${name}"]`)];
                  const el = radios[idx]; if (!el) return 'no-el';
                  (el.closest('label') || el).click();
                  return el.checked ? 'checked' : 'NOT-checked';
                }""", {"name": f["name"], "idx": idx})
                if ok != "checked":
                    raise RuntimeError(f"mood click did not stick: {ok}")
            elif f["kind"] == "select":
                # ponytail: JS set + change event — styled selects aren't action-ready for select_option.
                page.evaluate("""({name, value}) => {
                  const root = document.querySelector('div.modal.show') || document;
                  const sel = root.querySelector(`select[name="${name}"]`) || root.querySelector(`select[id="${name}"]`);
                  if (!sel) return;
                  const opt = [...sel.options].find((o) => (o.textContent || '').trim() === value) || sel.options[0];
                  sel.value = opt.value;
                  sel.dispatchEvent(new Event('change', {bubbles:true}));
                }""", {"name": f["name"], "value": val})
            elif f["kind"] == "checkbox":
                loc = page.locator(f'input[type="checkbox"][name="{f["name"]}"]').first
                if val and val.lower() not in ("no", "false"):
                    loc.check(timeout=3000, force=True)
                else:
                    loc.uncheck(timeout=3000, force=True)
            else:
                page.evaluate("""({name, value, tag}) => {
                  const el = [...document.querySelectorAll(`${tag}[name="${name}"]`)].find((c) => {
                    const r = c.getBoundingClientRect(); const s = window.getComputedStyle(c);
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0; });
                  if (!el) return;
                  const proto = tag === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                  Object.getOwnPropertyDescriptor(proto, 'value')?.set?.call(el, value);
                  el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true}));
                }""", {"name": f["name"], "value": val, "tag": "textarea" if f["kind"] == "textarea" else "input"})
            filled += 1
            log(f'filled "{f.get("label") or f.get("name")}" = "{val[:40]}"', "form")
        except Exception as e:
            log(f'failed to fill "{f.get("label") or f.get("name")}": {str(e).splitlines()[0] if str(e) else e}', "form")
    return filled


def submit_form(page):
    for sel in SUBMIT_CANDIDATES:
        try:
            loc = page.locator(f"{sel}:visible").first
            if loc.is_visible():
                loc.click(timeout=3000)
                log(f"submitted via {sel}", "form")
                return True
        except Exception:
            continue
    log("no submit button found", "form")
    return False


def run_checkin(force=False):
    # ponytail: local guard skips browser entirely when today already won. Server text stays fallback.
    if not force and is_done_today():
        msg = f"Already checked in today ({today_str()}) — skipping browser. Use --force to rerun."
        log(msg)
        append_run_log("skip-already-done | local guard hit")
        return 0
    ok, err = preflight_check()
    if not ok:
        log(f"Pre-flight check failed: {err}")
        notify_failure(err)
        return 1
    config = json.loads(SELECTOR_PATH.read_text(encoding="utf-8"))
    if not config.get("pageUrl") or not config.get("strategies"):
        print("[checkin] selector.json has no button saved (only doneMarkers). Run `python checkin.py --discover` first.")
        return 1
    log(f"Loaded config saved at {config.get('savedAt')} for URL: {config.get('pageUrl')}")
    log("Launching automation Chrome profile (headed). Main Chrome can stay open.")
    outcome, detail, code = "unknown", "", 0
    with sync_playwright() as p:
        context = launch_chrome(p)
        page = first_page(context)
        try:
            page.goto(config["pageUrl"], wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            log(f"Landed on: {page.url}")
            from urllib.parse import urlparse
            if re.search(r"/login(\?|/|$)", urlparse(page.url).path):
                if try_auto_login(page):
                    page.goto(config["pageUrl"], wait_until="domcontentloaded", timeout=30000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    log(f"Landed on: {page.url}")
                else:
                    detail = "Redirected to login. Set DICODING_EMAIL/DICODING_PASSWORD env vars or run `python checkin.py --discover` to log in again."
                    log(detail)
                    save_screenshot(page, "session_expired")
                    outcome, code = "session-expired", 2
                    notify_failure(detail)
                    return code
            if looks_already_checked_in(page):
                detail = "Page reports already checked in today — nothing to do."
                log(detail)
                save_screenshot(page, "already_checked_in")
                outcome = "already-checked-in"
                write_last_success()
                return 0
            button = find_button(page, config.get("strategies", []))
            if not button:
                if looks_already_checked_in(page):
                    detail = "Button absent and page reads as already-checked-in — nothing to do."
                    log(detail)
                    save_screenshot(page, "already_checked_in")
                    outcome = "already-checked-in"
                    write_last_success()
                    return 0
                dump = dump_page_text(page, "button_not_found")
                detail = ("No selector strategy matched. Page text saved: " + dump)
                log(detail)
                save_screenshot(page, "button_not_found")
                outcome, code = "button-not-found", 3
                notify_failure(detail)
                return code
            log("Clicking check-in button...")
            button.click(timeout=5000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(1500)
            fields = enumerate_form(page)
            if fields:
                if not ANSWERS_PATH.exists():
                    detail = f"Form detected with {len(fields)} fields but form-answers.json missing."
                    log(detail)
                    save_screenshot(page, "missing_answers_file")
                    outcome, code = "missing-answers", 1
                    notify_failure(detail)
                    return code
                parsed = json.loads(ANSWERS_PATH.read_text(encoding="utf-8"))
                raw = parsed.get("answers", parsed) if isinstance(parsed, dict) else {}
                today = {k: pick_daily(v) for k, v in raw.items() if not k.startswith("_")}
                log(f"Form detected with {len(fields)} fields — filling from form-answers.json")
                missing = [f for f in fields if f["kind"] != "checkbox" and today.get(f["label"]) is None and today.get(f["name"]) is None]
                if missing:
                    detail = "Missing answers: " + " | ".join(f.get("label") or f.get("name") for f in missing)
                    log(detail)
                    log("Not submitting partial form. Update form-answers.json, then run again.")
                    save_screenshot(page, "missing_answers")
                    outcome, code = "missing-answers", 1
                    notify_failure(detail)
                    return code
                if fill_form(page, fields, today) != len(fields) or not submit_form(page):
                    detail = "Failed to fill all fields or submit form."
                    log(detail)
                    save_screenshot(page, "submit_failed")
                    outcome, code = "submit-failed", 1
                    notify_failure(detail)
                    return code
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                page.wait_for_timeout(1500)
                # ponytail: one reload confirms persisted state (streak/Terisi render after reload).
                try:
                    page.reload(wait_until="domcontentloaded", timeout=30000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    page.wait_for_timeout(1500)
                except Exception:
                    pass
            shot = save_screenshot(page, "after_click")
            try:
                # ponytail: fresh probe — old locator may be detached after submit/reload.
                probe = page.locator(config["strategies"][0]["selector"]).first
                still_there = probe.is_visible()
            except Exception:
                still_there = False
            if looks_already_checked_in(page) or not still_there:
                outcome = "clicked-verified"
                detail = "Clicked; success signals detected (button gone / already-checked-in text)."
                write_last_success()
            else:
                outcome, detail, code = "clicked-unverified", "Clicked, no success signals. Verify via screenshot.", 1
                notify_failure(detail)
            log(detail)
            log(f"Screenshot: {shot}")
            return code
        except Exception as e:
            outcome, detail, code = "error", str(e).splitlines()[0] if str(e) else repr(e), 4
            log(f"Error: {detail}")
            try:
                save_screenshot(page, "error")
            except Exception:
                pass
            return code
        finally:
            append_run_log(f"{outcome} | {detail}")
            # ponytail: closes only the automation window, main Chrome untouched.
            try:
                context.close()
            except Exception:
                pass


def resolve_session_duplication(page):
    # ponytail: one known wall, one known button. No generic popup framework.
    try:
        dup = "session-duplication" in (page.url or "")
        if not dup:
            try:
                dup = "Akun Terdeteksi Pada Browser Lain" in (page.evaluate("() => document.body?.innerText ?? ''") or "")
            except Exception:
                dup = False
        if not dup:
            return True
        log("Session-duplication wall — taking over in this browser.", "auth")
        page.locator('button:has-text("Lanjut di browser ini")').first.click(timeout=8000)
        page.wait_for_timeout(2000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        return "session-duplication" not in (page.url or "")
    except Exception as e:
        log(f"Duplication resolve failed: {str(e).splitlines()[0] if str(e) else e}", "auth")
        return False


def try_auto_login(page):
    # ponytail: env creds only — never logged, never written anywhere. Captcha/manual stays fallback.
    email, password = os.environ.get("DICODING_EMAIL", ""), os.environ.get("DICODING_PASSWORD", "")
    if not email or not password:
        return False
    try:
        log("Trying auto-login from env credentials.", "auth")
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        page.locator('input[name="login_email"]:visible').fill(email, timeout=10000)
        page.locator('input[name="login_password"]:visible').fill(password, timeout=10000)
        page.locator('#login-form button[type="submit"]:visible, #login-form button:has-text("Masuk")').first.click(timeout=5000)
        page.wait_for_timeout(2000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        from urllib.parse import urlparse
        if not resolve_session_duplication(page):
            log("Auto-login stuck on session-duplication wall.", "auth")
            return False
        if re.search(r"/login(\?|/|$)", urlparse(page.url).path):
            log("Auto-login failed (still on login — wrong creds or captcha).", "auth")
            return False
        log("Auto-login ok.", "auth")
        return True
    except Exception as e:
        log(f"Auto-login error: {str(e).splitlines()[0] if str(e) else e}", "auth")
        return False


def is_logged_in(page):
    try:
        return bool(page.evaluate("""() => {
          const t = document.body?.innerText ?? '';
          const out = ['Masuk','Daftar'].some((m) => new RegExp(`\\\\b${m}\\\\b`).test(t));
          const inn = ['Keluar','Logout','My Account','Akun Saya','Dashboard'].some((m) => new RegExp(`\\\\b${m}\\\\b`, 'i').test(t));
          return inn && !out; }"""))
    except Exception:
        return False


def is_google_trap(url):
    try:
        from urllib.parse import urlparse, parse_qs
        u = urlparse(url)
        return u.hostname == "accounts.google.com" or (u.hostname or "").endswith(".accounts.google.com") \
            or re.search(r"/rejected", u.path, re.I) or "oauth_error" in parse_qs(u.query)
    except Exception:
        return False


def find_candidates(page):
    out = []
    frames = [page.main_frame] + [f for f in page.frames if f != page.main_frame]

    # ponytail: JS held as one string, not per-frame builder. Ceiling: cross-origin iframes skipped silently.
    def scan(frame, in_iframe):
        try:
            return frame.evaluate("""(hints) => {
              const esc = (s) => s.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\$&');
              const pats = hints.map((h) => new RegExp(esc(h).replace(/\\?\\s+/g, '\\s+'), 'i'));
              const out = [];
              for (const el of document.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"], div[onclick], [class*="checkin" i], [class*="check-in" i], [id*="checkin" i], [id*="check-in" i]')) {
                const s = window.getComputedStyle(el);
                if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) < 0.1) continue;
                const text = (el.textContent ?? '').replace(/\\s+/g, ' ').trim();
                const cls = (el.className?.toString?.() ?? '');
                if (!(pats.some((q) => q.test(text)) || pats.some((q) => q.test(cls)) || pats.some((q) => q.test(el.id ?? '')))) continue;
                if (text.length > 120) continue;
                const r = el.getBoundingClientRect();
                if (r.width === 0 && r.height === 0) continue;
                out.push({text, tag: el.tagName.toLowerCase(),
                  rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}});
              }
              const seen = new Set();
              return out.filter((c) => { const k = `${c.text}|${c.rect.x}|${c.rect.y}`; if (seen.has(k)) return false; seen.add(k); return true; });
            }""", CHECKIN_TEXT_HINTS)
        except Exception:
            return []
    for i, fr in enumerate(frames):
        for c in scan(fr, i > 0):
            out.append({**c, "in_iframe": i > 0})
    return [{"idx": i + 1, **c} for i, c in enumerate(out)]


def build_strategies(page, chosen):
    t = chosen["text"].replace('"', '\\"')
    strategies = [
        {"desc": "button/link with exact text", "selector": f':is(button, a, [role="button"]):has-text("{t}")'},
        {"desc": "any element with text", "selector": f'text={chosen["text"][:60]}'},
    ]
    if chosen.get("in_iframe"):
        return strategies
    try:
        hit = page.evaluate("""(rect) => {
          const hit = [...document.querySelectorAll('*')].find((el) => { const r = el.getBoundingClientRect();
            return Math.abs(r.x-rect.x)<3 && Math.abs(r.y-rect.y)<3 && Math.abs(r.width-rect.w)<3 && Math.abs(r.height-rect.h)<3; });
          if (!hit) return null;
          const attrs = {};
          for (const a of hit.attributes) if (a.name.startsWith('data-') && a.value) attrs[a.name] = a.value;
          return {tag: hit.tagName.toLowerCase(), id: hit.id, attrs}; }""", chosen["rect"])
    except Exception:
        hit = None
    if hit:
        if hit.get("id"):
            strategies.append({"desc": "element id", "selector": f'#{hit["id"]}'})
        for k, v in (hit.get("attrs") or {}).items():
            strategies.append({"desc": f'attribute {k}="{v}"', "selector": f'[{k}="{v}"]'})
    return strategies


def run_discover():
    log("Starting interactive discovery...", "discover")
    with sync_playwright() as p:
        context = launch_chrome(p)
        page = first_page(context)
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            logged = try_auto_login(page)
            if not logged:
                log("Browser opened on Dicoding login. Log in (email+password; Google OAuth blocked in automation).", "discover")
            deadline = time.time() + 10 * 60
            last = time.time()
            while time.time() < deadline:
                if is_google_trap(page.url):
                    print("\nGOOGLE LOGIN TRAP — use EMAIL+PASSWORD, not Google button. Back to login...\n")
                    try:
                        page.goto(LOGIN_URL, wait_until="domcontentloaded")
                    except Exception:
                        pass
                    continue
                logged = is_logged_in(page)
                if logged:
                    break
                resolve_session_duplication(page)
                if time.time() - last > 15:
                    log(f"Still waiting... current page: {page.url}", "discover")
                    last = time.time()
                page.wait_for_timeout(2000)
            if not logged:
                print("[discover] Timed out waiting for login.")
                return 1
            log("Looks logged in!", "discover")
            target = input("\nPaste check-in page URL (Enter if already there): ").strip()
            if target:
                if not re.match(r"https?://", target, re.I):
                    target = "https://" + target
                log(f"Navigating to {target} ...", "discover")
                page.goto(target, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            log(f"Current URL: {page.url}", "discover")
            cands = find_candidates(page)
            if not cands:
                if looks_already_checked_in(page):
                    print("\n[discover] Page says ALREADY CHECKED IN — button hidden. Re-run discover tomorrow when visible.")
                    return 0
                dump = dump_page_text(page, "discover_no_candidates")
                print(f"[discover] No candidates. Page text: {dump}")
                phrase = input("Paste exact already-checked-in phrase to teach (Enter to skip): ").strip()
                if phrase:
                    add_custom_done_markers([phrase])
                    print(f'[discover] Recorded "{phrase}". checkin will now recognize it.')
                    return 0
                print("[discover] Navigate to button page, re-run discover.")
                return 1
            print("\nFound candidates:")
            for c in cands:
                print(f'  {c["idx"]}. [{"iframe, " if c["in_iframe"] else ""}<{c["tag"]}>] "{c["text"]}" @ ({c["rect"]["x"]},{c["rect"]["y"]})')
            try:
                choice = int(input("\nWhich number is the check-in button? ").strip())
            except ValueError:
                choice = -1
            chosen = next((c for c in cands if c["idx"] == choice), None)
            if not chosen:
                print("[discover] Invalid choice.")
                return 1
            strategies = build_strategies(page, chosen)
            prev = read_json(SELECTOR_PATH, {}) or {}
            cfg = {"pageUrl": page.url, "strategies": strategies, "visibleText": chosen["text"],
                   "savedAt": datetime.datetime.now(datetime.timezone.utc).isoformat()}
            if isinstance(prev.get("doneMarkers"), list) and prev["doneMarkers"]:
                cfg["doneMarkers"] = prev["doneMarkers"]
            SELECTOR_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
            log(f"Saved -> {SELECTOR_PATH}", "discover")
            if input("\nTest primary selector now (clicks for real!)? [y/N]: ").strip().lower() == "y":
                try:
                    page.locator(strategies[0]["selector"]).first.click(timeout=5000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    page.wait_for_timeout(1500)
                    fields = enumerate_form(page)
                    if fields:
                        print("\nFORM DETECTED — author these keys in form-answers.json:")
                        for f in fields:
                            print(f'  kind={f["kind"]} name="{f["name"]}" label="{f["label"]}"' +
                                  (f' options=[{" | ".join(f["options"])}]' if f.get("options") else ""))
                    else:
                        log("No form after click (toast/modal-only flow).", "discover")
                except Exception as e:
                    log(f"Click test failed: {str(e).splitlines()[0] if str(e) else e}", "discover")
            print("\n=== Discovery complete ===\nNext: python checkin.py")
            return 0
        finally:
            try:
                context.close()
            except Exception:
                pass


def selftest():
    assert pick_daily("fixed") == "fixed"
    assert pick_daily(["a", "b", "c"]) in ("a", "b", "c")
    assert pick_daily({"weekday": ["x"], "weekend": ["y"]}) in ("x", "y")
    assert pick_daily([]) == ""
    # ponytail: guard roundtrip on temp path, real last-success.txt untouched.
    import tempfile
    global LAST_OK_PATH
    prev, tmp = LAST_OK_PATH, pathlib.Path(tempfile.mkdtemp()) / "last-success.txt"
    try:
        LAST_OK_PATH = tmp
        assert not is_done_today()
        write_last_success()
        assert is_done_today()
        assert read_last_success() == today_str()
    finally:
        LAST_OK_PATH = prev
    print("selftest ok")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Daily check-in automation for Dicoding Asah using headed Chrome.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-f", "--force", action="store_true", help="Bypass today-already-done guard")
    parser.add_argument("-d", "--discover", action="store_true", help="Run interactive selector discovery")
    parser.add_argument("-s", "--selftest", action="store_true", help="Run offline sanity selftests and exit")
    parser.add_argument("--no-pause", action="store_true", help="No-op flag for batch script compatibility")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    if args.selftest:
        selftest()
    elif args.discover:
        sys.exit(run_discover())
    else:
        sys.exit(run_checkin(force=args.force))
