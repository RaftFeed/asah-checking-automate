# Asah Daily Check-in Automation

Automated daily check-in script for the **Dicoding Asah** program using [Playwright](https://playwright.dev/python/) with an isolated, headed Google Chrome profile.

---

## Features

- **Isolated Chrome Profile**: Automates inside a dedicated `.chrome-profile/` directory. Your main Google Chrome browser can stay open while the script runs without lock conflicts.
- **Headed Automation**: Runs with a real browser window to avoid headless detection and bypass anti-bot mechanisms.
- **Smart Daily Guard**: Automatically tracks both the daily check-in form (`runs/last-success.txt`) and streak belajar (`runs/last-streak.txt`), skipping browser launches only when today's tasks are completed.
- **Streak Belajar Automation**: Automatically clicks "Lanjutkan" on your active learning subject under *Aktivitas Belajar* to preserve your daily learning streak.
- **Dynamic Form Rotation**:
  - Supports static answers (strings).
  - Rotates answers daily by day-of-month (`(day - 1) % len(list)`).
  - Supports weekday vs. weekend reflection pools.
- **Automatic Button Discovery**: Autonomously locates the "Mulai isi check-in" button under the *Daily Check-in* section without requiring manual selector configuration.
- **One-Click Batch Runner (`checkin.bat`)**: Double-click to run on Windows, ideal for Windows Task Scheduler or desktop shortcuts.

---

## Prerequisites

- **Python**: 3.10 or higher
- **Google Chrome**: Installed on your system (custom paths can be set via `CHROME_PATH`)

---

## Installation & Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/RaftFeed/asah-checking-automate.git
   cd asah-checking-automate
   ```

2. **Create and activate a virtual environment**:
   ```powershell
   # Windows PowerShell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
   ```bash
   # Linux / macOS
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

4. **Configure form answers**:
   Copy the example answers template to `form-answers.json`:
   ```bash
   # Windows
   copy form-answers.example.json form-answers.json

   # Linux / macOS
   cp form-answers.example.json form-answers.json
   ```
   Edit `form-answers.json` to match your registered class name and custom reflections.

5. **(Optional) Auto-login credentials**:
   Set environment variables if you want automatic credential fill on session expiry:
   ```powershell
   $env:DICODING_EMAIL="your-email@example.com"
   $env:DICODING_PASSWORD="your-password"
   ```

---

## Usage

### 1. Daily Check-in & Streak Belajar
Run manually or double-click `checkin.bat` (Windows):
```bash
python checkin.py
```
- Zero-config & autonomous: automatically detects "Mulai isi check-in" under the **Daily Check-in** section.
- By default, it executes both the **daily form check-in** and **streak belajar**.
- If a task is already completed today, it only runs the pending task (or skips if both are done).
- For streak belajar, it clicks "Lanjutkan" on the first active course under *Aktivitas Belajar* and stays on the tutorial page for 5 seconds to ensure streak registration.
- Screenshots are saved in `runs/` for verification.
- **For Windows Task Scheduler**: use `checkin.bat --no-pause` so the batch runner terminates cleanly after completion without waiting for keyboard input.

### 2. Additional Options
- **Trigger Streak Only** (skips form check-in):
  ```bash
  python checkin.py --streak-only
  ```
- **Skip Streak** (runs form check-in only):
  ```bash
  python checkin.py --no-streak
  ```
- **Bypass Daily Guard**:
  ```bash
  python checkin.py --force
  ```
- **Run Sanity Selftests**:
  ```bash
  python checkin.py --selftest
  ```
- **Run Full Unit Tests**:
  ```bash
  python -m unittest test_checkin.py -v
  ```

---

## Environment Variables

You can set these in your operating system environment or define them in a local `.env` file (which is automatically parsed at startup):

| Variable | Description |
|---|---|
| `DICODING_EMAIL` | *(Optional)* Email for automatic re-login if session expires |
| `DICODING_PASSWORD` | *(Optional)* Password for automatic re-login |
| `CHROME_PATH` | *(Optional)* Absolute path to `chrome.exe` if not in default install directory |

---

## Privacy & Security

The following runtime files are automatically excluded by `.gitignore` and **never committed**:
- `.chrome-profile/` — Contains browser session cookies and tokens.
- `form-answers.json` — Your course name and personal study reflection notes.
- `selector.json` — Generated selector paths and timestamps.
- `runs/` — Output logs and screenshots of your logged-in dashboard.
- `.env` — Local environment variables.

---

## License

[MIT](LICENSE)
