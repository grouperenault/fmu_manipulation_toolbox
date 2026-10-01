"""Integration tests for Model-Exchange container support.

Migrated from the legacy ``test_suite.py``. The legacy tests looped over three
orchestration configurations; they are now expanded with
``@pytest.mark.parametrize`` for clearer reporting (one test id per config).
Each case runs in an isolated copy of ``tests/data/me``.
"""
import sys

import pytest

from fmu_manipulation_toolbox.assembly import Assembly

from _helpers.simulation import assert_simulation

pytestmark = [pytest.mark.integration, pytest.mark.fmi2, pytest.mark.area("me")]

WIN = sys.platform == "win32"

CONFIGS = [
    {"default_mt": True, "default_sequential": False},
    {"default_mt": False, "default_sequential": True},
    {"default_mt": False, "default_sequential": False},
]
CONFIG_IDS = ["mt", "sequential", "plain"]


@pytest.mark.parametrize("config", CONFIGS, ids=CONFIG_IDS)
def test_me(area_dir, config):
    assembly = Assembly("bouncing_ball_me.json", debug=True, **config)
    assembly.make_fmu(fmi_version=2)
    if WIN:
        assert_simulation("bouncing_ball_me.fmu", 0.1)


@pytest.mark.parametrize("config", CONFIGS, ids=CONFIG_IDS)
def test_me_mix(area_dir, config):
    assembly = Assembly("bouncing_ball_mix.json", debug=True, **config)
    assembly.make_fmu(fmi_version=2)
    if WIN:
        assert_simulation("bouncing_ball_mix.fmu", 0.1)

