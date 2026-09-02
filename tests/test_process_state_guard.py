"""The guard that fails a test for leaving shared process state changed.

Issue #263: under ``pytest -n auto`` every test on one xdist worker shares
one ``src.app`` module object, so a config key or a module attribute left
changed decides it for every test that lands after it.  The failures were
whole-file cascades in files the diff never touched, green serially and
green on rerun.  ``tests/conftest.py`` brackets each test with
``tests/process_state.py``; what is here is the red it can produce, the
restore that keeps one leak from failing the next test too, and the
absent-versus-``None`` distinction that made the leak possible.
"""

import pytest

import src.app as app_module
from tests import process_state
from tests.app_config import app_config


class TestTheGuardGoesRedOnDemand:
    """R-05: the check is driven by a real leak, not trusted empty."""

    def test_a_changed_config_key_is_reported_and_put_back(self):
        before = process_state.snapshot()
        app_module.app.config["RATE_LIMIT_ENABLED"] = "leaked"

        report = process_state.restore_and_report(before)

        assert report == ["src.app.app.config['RATE_LIMIT_ENABLED']: True -> 'leaked'"]
        assert app_module.app.config["RATE_LIMIT_ENABLED"] is True

    def test_a_rebound_module_attribute_is_reported_and_put_back(self):
        """``app_module.calculate_payload = ...`` is the issue's own suspect."""
        original = app_module.calculate_payload
        before = process_state.snapshot()
        app_module.calculate_payload = lambda *_args, **_kwargs: None

        report = process_state.restore_and_report(before)

        assert [line.split(":")[0] for line in report] == ["src.app.calculate_payload"]
        assert app_module.calculate_payload is original

    def test_a_deleted_config_key_is_reported_and_put_back(self):
        before = process_state.snapshot()
        del app_module.app.config["PROPAGATE_EXCEPTIONS"]

        report = process_state.restore_and_report(before)

        assert report == [
            "src.app.app.config['PROPAGATE_EXCEPTIONS']: None -> <absent>"
        ]
        assert app_module.app.config["PROPAGATE_EXCEPTIONS"] is None

    def test_an_equal_value_counts_as_given_back(self):
        """``db.reset()`` rebinds to a fresh empty dict; that is a restore."""
        before = process_state.snapshot()
        app_module.app.config["OPTIMIZER_INSTRUMENTATION"] = {}

        assert process_state.restore_and_report(before) == []

    def test_the_guard_brackets_this_very_test(self, request):
        """The fixture is autouse rather than opted into per file."""
        assert "_process_state_is_given_back" in request.fixturenames


class TestTheBorrowRestoresAbsentAndNoneApart:
    """``config.get`` cannot tell them apart, and Flask has such a key."""

    def test_a_none_valued_key_comes_back_present(self):
        with app_config(PROPAGATE_EXCEPTIONS=False):
            assert app_module.app.config["PROPAGATE_EXCEPTIONS"] is False

        assert "PROPAGATE_EXCEPTIONS" in app_module.app.config
        assert app_module.app.config["PROPAGATE_EXCEPTIONS"] is None

    def test_a_key_that_was_absent_goes_back_to_absent(self):
        with app_config(A_KEY_FLASK_NEVER_DEFINES=1):
            assert app_module.app.config["A_KEY_FLASK_NEVER_DEFINES"] == 1

        assert "A_KEY_FLASK_NEVER_DEFINES" not in app_module.app.config

    def test_the_block_gives_back_what_it_changed_outside_its_overrides(self):
        """A test driving a script gets the script's writes undone too."""
        with app_config():
            app_module.app.config["RATE_LIMIT_ENABLED"] = "script wrote this"

        assert app_module.app.config["RATE_LIMIT_ENABLED"] is True

    def test_deleting_the_key_turns_the_next_route_error_into_a_key_error(
        self, monkeypatch
    ):
        """Why the distinction has teeth: Flask reads the key by subscript.

        ``handle_exception`` does ``self.config["PROPAGATE_EXCEPTIONS"]``, so
        a worker whose config lost the key answers the next unhandled route
        error with ``KeyError`` instead of the 500 the test expects -- in a
        file that never touched it.
        """
        from src.calculator import scenario

        def boom(_champion_name):
            raise RuntimeError("issue 263 probe")

        monkeypatch.setattr(scenario, "load_public_champion", boom)
        request = {"champion": "Ahri", "level": 18, "items": []}

        with app_config(TESTING=False, PROPAGATE_EXCEPTIONS=None):
            served = app_module.app.test_client().post("/api/calculate", json=request)
            assert served.status_code == 500

            del app_module.app.config["PROPAGATE_EXCEPTIONS"]
            with pytest.raises(KeyError, match="PROPAGATE_EXCEPTIONS"):
                app_module.app.test_client().post("/api/calculate", json=request)
