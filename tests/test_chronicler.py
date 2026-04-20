"""Tests for agents/chronicler/{scrapers,agent}.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# scrapers.tokei_unitares_src_code
# ---------------------------------------------------------------------------


class TestTokeiScraper:
    def test_counts_lines_in_real_src(self, tmp_path: Path):
        from agents.chronicler.scrapers import tokei_unitares_src_code

        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("print(1)\nprint(2)\nprint(3)\n")
        (src / "b.py").write_text("x = 1\n")
        (src / "ignored.js").write_text("// not python\nstill not\n")

        value = tokei_unitares_src_code(tmp_path)
        # 3 + 1 = 4; the .js file must not count.
        assert value == 4.0

    def test_empty_src_returns_zero(self, tmp_path: Path):
        from agents.chronicler.scrapers import tokei_unitares_src_code

        (tmp_path / "src").mkdir()
        assert tokei_unitares_src_code(tmp_path) == 0.0

    def test_missing_src_raises(self, tmp_path: Path):
        from agents.chronicler.scrapers import tokei_unitares_src_code

        with pytest.raises(FileNotFoundError):
            tokei_unitares_src_code(tmp_path)


class TestTestsCountScraper:
    def test_counts_only_test_prefixed_py_files(self, tmp_path: Path):
        from agents.chronicler.scrapers import tests_unitares_count

        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_a.py").write_text("")
        (tests / "test_b.py").write_text("")
        (tests / "conftest.py").write_text("")        # not test_*.py — excluded
        (tests / "helper_utils.py").write_text("")    # not test_*.py — excluded
        (tests / "notes.md").write_text("")           # not python — excluded

        sub = tests / "sub"
        sub.mkdir()
        (sub / "test_nested.py").write_text("")       # nested test_*.py — counted

        assert tests_unitares_count(tmp_path) == 3.0

    def test_empty_tests_dir_returns_zero(self, tmp_path: Path):
        from agents.chronicler.scrapers import tests_unitares_count

        (tmp_path / "tests").mkdir()
        assert tests_unitares_count(tmp_path) == 0.0

    def test_missing_tests_dir_raises(self, tmp_path: Path):
        from agents.chronicler.scrapers import tests_unitares_count

        with pytest.raises(FileNotFoundError):
            tests_unitares_count(tmp_path)


# ---------------------------------------------------------------------------
# agent.run
# ---------------------------------------------------------------------------


class FakeHttpResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class FakeHttpClient:
    """Tracks calls to client.post so we can assert payload/url/auth shape."""

    def __init__(self, response: FakeHttpResponse | None = None):
        self.calls: list[dict] = []
        self._response = response or FakeHttpResponse(201)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, *, headers, content, timeout):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "body": json.loads(content),
                "timeout": timeout,
            }
        )
        return self._response


class TestAgentRun:
    def test_success_case_posts_each_scraper(self, tmp_path: Path):
        from agents.chronicler import agent as chronicler

        fake = FakeHttpClient()
        scrapers = {
            "tokei.unitares.src.code": lambda _root: 70000.0,
            "tests.unitares.count": lambda _root: 6601.0,
        }

        with (
            patch.object(chronicler, "SCRAPERS", scrapers),
            patch("agents.chronicler.agent.httpx.Client", return_value=fake),
        ):
            ok, fail = chronicler.run("http://127.0.0.1:8767", token=None, repo_root=tmp_path)

        assert ok == 2
        assert fail == 0
        assert len(fake.calls) == 2
        names = {call["body"]["name"] for call in fake.calls}
        assert names == {"tokei.unitares.src.code", "tests.unitares.count"}

    def test_dry_run_does_not_post(self, tmp_path: Path):
        from agents.chronicler import agent as chronicler

        fake = FakeHttpClient()
        with (
            patch.object(chronicler, "SCRAPERS", {"x.y.z": lambda _r: 1.0}),
            patch("agents.chronicler.agent.httpx.Client", return_value=fake),
        ):
            ok, fail = chronicler.run(
                "http://127.0.0.1:8767", token=None, repo_root=tmp_path, dry_run=True
            )

        assert ok == 1
        assert fail == 0
        assert fake.calls == []

    def test_scrape_failure_emits_error_metric(self, tmp_path: Path):
        from agents.chronicler import agent as chronicler

        fake = FakeHttpClient()

        def boom(_root):
            raise RuntimeError("tokei missing")

        with (
            patch.object(chronicler, "SCRAPERS", {"tokei.unitares.src.code": boom}),
            patch("agents.chronicler.agent.httpx.Client", return_value=fake),
        ):
            ok, fail = chronicler.run("http://127.0.0.1:8767", token=None, repo_root=tmp_path)

        assert ok == 0
        assert fail == 1
        assert len(fake.calls) == 1
        error_call = fake.calls[0]
        assert error_call["body"]["name"] == "tokei.unitares.src.code.error"
        assert error_call["body"]["value"] == 1.0

    def test_http_error_counts_as_failure_but_does_not_raise(self, tmp_path: Path):
        from agents.chronicler import agent as chronicler

        fake = FakeHttpClient(response=FakeHttpResponse(500, "boom"))
        with (
            patch.object(chronicler, "SCRAPERS", {"x.y.z": lambda _r: 1.0}),
            patch("agents.chronicler.agent.httpx.Client", return_value=fake),
        ):
            ok, fail = chronicler.run("http://127.0.0.1:8767", token=None, repo_root=tmp_path)

        assert ok == 0
        assert fail == 1

    def test_bearer_token_header_included(self, tmp_path: Path):
        from agents.chronicler import agent as chronicler

        fake = FakeHttpClient()
        with (
            patch.object(chronicler, "SCRAPERS", {"x.y.z": lambda _r: 1.0}),
            patch("agents.chronicler.agent.httpx.Client", return_value=fake),
        ):
            chronicler.run("http://127.0.0.1:8767", token="secret-123", repo_root=tmp_path)

        assert fake.calls[0]["headers"]["authorization"] == "Bearer secret-123"

    def test_post_error_metric_survives_if_server_unreachable(self, tmp_path: Path):
        """If the post-error call itself fails, we still complete the loop."""
        from agents.chronicler import agent as chronicler

        class AlwaysFails:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def post(self, *a, **kw):
                raise RuntimeError("network down")

        def boom(_root):
            raise RuntimeError("scrape failed")

        with (
            patch.object(chronicler, "SCRAPERS", {"x.y.z": boom}),
            patch("agents.chronicler.agent.httpx.Client", return_value=AlwaysFails()),
        ):
            ok, fail = chronicler.run("http://127.0.0.1:8767", token=None, repo_root=tmp_path)

        assert ok == 0
        assert fail == 1  # scrape failure counted, post-error failure swallowed
