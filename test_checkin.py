import datetime
import os
import pathlib
import tempfile
import unittest

import checkin

class TestDotenvAndDate(unittest.TestCase):
    def test_load_dotenv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = pathlib.Path(tmpdir) / ".env"
            env_file.write_text(
                "# Comment\n"
                "TEST_DICODING_VAR=hello_world\n"
                "TEST_QUOTED='single_value'\n"
                "TEST_DOUBLE=\"double_value\"\n"
                "INVALID_LINE\n"
                "   \n",
                encoding="utf-8"
            )
            # Monkeypatch HERE to tmpdir
            orig_here = checkin.HERE
            try:
                checkin.HERE = pathlib.Path(tmpdir)
                if "TEST_DICODING_VAR" in os.environ:
                    del os.environ["TEST_DICODING_VAR"]
                checkin.load_dotenv()
                self.assertEqual(os.environ.get("TEST_DICODING_VAR"), "hello_world")
                self.assertEqual(os.environ.get("TEST_QUOTED"), "single_value")
                self.assertEqual(os.environ.get("TEST_DOUBLE"), "double_value")
            finally:
                checkin.HERE = orig_here
                os.environ.pop("TEST_DICODING_VAR", None)
                os.environ.pop("TEST_QUOTED", None)
                os.environ.pop("TEST_DOUBLE", None)

    def test_today_str_wib_timezone(self):
        # Verify WIB is UTC+7
        wib = checkin.WIB
        self.assertEqual(wib.utcoffset(None), datetime.timedelta(hours=7))
        # Verify today_str returns YYYY-MM-DD
        s = checkin.today_str()
        self.assertRegex(s, r"^\d{4}-\d{2}-\d{2}$")

    def test_reflection_dedup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_runs = checkin.RUNS_DIR
            orig_ref = checkin.LAST_REFLECTION_PATH
            try:
                checkin.RUNS_DIR = pathlib.Path(tmpdir)
                checkin.LAST_REFLECTION_PATH = checkin.RUNS_DIR / "last-reflection.txt"
                pool = {"weekday": ["text1", "text2"]}
                # Force last pick to text1
                checkin.LAST_REFLECTION_PATH.write_text("text1", encoding="utf-8")
                # When picking, it should avoid text1 since pool has 2 items
                pick = checkin.pick_daily(pool)
                self.assertEqual(pick, "text2")
                self.assertEqual(checkin.LAST_REFLECTION_PATH.read_text(encoding="utf-8").strip(), "text2")
            finally:
                checkin.RUNS_DIR = orig_runs
                checkin.LAST_REFLECTION_PATH = orig_ref

    def test_preflight_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = pathlib.Path(tmpdir)
            orig_sel = checkin.SELECTOR_PATH
            orig_ans = checkin.ANSWERS_PATH
            try:
                checkin.SELECTOR_PATH = tmp / "selector.json"
                checkin.ANSWERS_PATH = tmp / "form-answers.json"

                # 1. Missing selector.json
                ok, err = checkin.preflight_check()
                self.assertFalse(ok)
                self.assertIn("selector.json not found", err)

                # 2. Invalid selector.json
                checkin.SELECTOR_PATH.write_text('{"pageUrl": "https://example.com"}', encoding="utf-8")
                ok, err = checkin.preflight_check()
                self.assertFalse(ok)
                self.assertIn("invalid", err.lower())

                # 3. Valid selector, invalid form-answers.json
                checkin.SELECTOR_PATH.write_text(
                    '{"pageUrl": "https://example.com", "strategies": [{"selector": "button"}]}',
                    encoding="utf-8"
                )
                checkin.ANSWERS_PATH.write_text('{ invalid json }', encoding="utf-8")
                ok, err = checkin.preflight_check()
                self.assertFalse(ok)
                self.assertIn("syntax error", err.lower())

                # 4. Valid selector and valid form-answers
                checkin.ANSWERS_PATH.write_text('{"answers": {}}', encoding="utf-8")
                ok, err = checkin.preflight_check()
                self.assertTrue(ok)
                self.assertEqual(err, "")
            finally:
                checkin.SELECTOR_PATH = orig_sel
                checkin.ANSWERS_PATH = orig_ans

    def test_parse_args(self):
        args = checkin.parse_args(["--force"])
        self.assertTrue(args.force)
        self.assertFalse(args.discover)
        self.assertFalse(args.selftest)

        args2 = checkin.parse_args(["-d"])
        self.assertTrue(args2.discover)

        args3 = checkin.parse_args(["--no-pause"])
        self.assertTrue(args3.no_pause)

    def test_streak_state_tracking(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_runs = checkin.RUNS_DIR
            orig_streak = checkin.LAST_STREAK_PATH
            try:
                checkin.RUNS_DIR = pathlib.Path(tmpdir)
                checkin.LAST_STREAK_PATH = checkin.RUNS_DIR / "last-streak.txt"
                self.assertFalse(checkin.is_streak_done_today())
                self.assertEqual(checkin.read_last_streak(), "")
                checkin.write_last_streak()
                self.assertTrue(checkin.is_streak_done_today())
                self.assertEqual(checkin.read_last_streak(), checkin.today_str())
            finally:
                checkin.RUNS_DIR = orig_runs
                checkin.LAST_STREAK_PATH = orig_streak

    def test_parse_args_streak(self):
        args = checkin.parse_args(["--streak-only"])
        self.assertTrue(args.streak_only)
        self.assertFalse(args.no_streak)

        args2 = checkin.parse_args(["--no-streak"])
        self.assertFalse(args2.streak_only)
        self.assertTrue(args2.no_streak)

    def test_plan_run_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_runs = checkin.RUNS_DIR
            orig_ok = checkin.LAST_OK_PATH
            orig_streak = checkin.LAST_STREAK_PATH
            try:
                checkin.RUNS_DIR = pathlib.Path(tmpdir)
                checkin.LAST_OK_PATH = checkin.RUNS_DIR / "last-success.txt"
                checkin.LAST_STREAK_PATH = checkin.RUNS_DIR / "last-streak.txt"

                # 1. Neither done
                self.assertEqual(checkin.plan_run_tasks(), (True, True))

                # 2. Checkin done, streak not done
                checkin.write_last_success()
                self.assertEqual(checkin.plan_run_tasks(), (False, True))

                # 3. Both done, force=False
                checkin.write_last_streak()
                self.assertEqual(checkin.plan_run_tasks(), (False, False))

                # 4. Both done, force=True
                self.assertEqual(checkin.plan_run_tasks(force=True), (True, True))

                # 5. streak_only
                self.assertEqual(checkin.plan_run_tasks(streak_only=True), (False, False))
                self.assertEqual(checkin.plan_run_tasks(force=True, streak_only=True), (False, True))

                # Reset streak to not done
                checkin.LAST_STREAK_PATH.unlink()
                self.assertEqual(checkin.plan_run_tasks(streak_only=True), (False, True))

                # 6. no_streak
                self.assertEqual(checkin.plan_run_tasks(no_streak=True), (False, False))
                self.assertEqual(checkin.plan_run_tasks(force=True, no_streak=True), (True, False))
            finally:
                checkin.RUNS_DIR = orig_runs
                checkin.LAST_OK_PATH = orig_ok
                checkin.LAST_STREAK_PATH = orig_streak


class TestFindContinueButton(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.page = self.browser.new_page()

    def tearDown(self):
        self.page.close()

    def test_find_first_active_course_continue(self):
        html = """
        <div class="card">
          <h3>Aktivitas Belajar</h3>
          <div class="item">
            <span>Sedang dipelajari</span>
            <h4>Belajar Dasar Pemrograman JavaScript</h4>
            <a href="/academies/123/tutorials/1" class="btn">Lanjutkan</a>
          </div>
          <div class="item">
            <span>Telah diselesaikan</span>
            <h4>Belajar Dasar Pemrograman Web</h4>
            <a href="/cert" class="btn">Cetak Sertifikat</a>
          </div>
          <div class="item">
            <span>Sedang dipelajari</span>
            <h4>Asah 2026 - ILT Soft Skill</h4>
            <a href="/academies/456/tutorials/2" class="btn">Lanjutkan</a>
          </div>
        </div>
        """
        self.page.set_content(html)
        btn = checkin.find_continue_button(self.page)
        self.assertIsNotNone(btn)
        self.assertEqual(btn.get_attribute("href"), "/academies/123/tutorials/1")

    def test_find_continue_returns_none_when_no_active(self):
        html = """
        <div class="card">
          <h3>Aktivitas Belajar</h3>
          <div class="item">
            <span>Telah diselesaikan</span>
            <h4>Belajar Dasar Pemrograman Web</h4>
            <a href="/cert" class="btn">Cetak Sertifikat</a>
          </div>
        </div>
        """
        self.page.set_content(html)
        btn = checkin.find_continue_button(self.page)
        self.assertIsNone(btn)


if __name__ == "__main__":
    unittest.main()


