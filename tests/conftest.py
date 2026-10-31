import os
import pathlib
import shutil

import pytest

from lab.topology import Lab


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call":
        item.failed_in_call = report.failed


@pytest.fixture
def lab(request):
    """A fresh network for every test, so one test's failure can't affect the next."""
    instance = Lab()
    try:
        instance.start()
        yield instance
    finally:
        # Keep daemon logs from failed tests, so failures can be debugged from CI artifacts.
        if getattr(request.node, "failed_in_call", True):
            target = pathlib.Path(os.environ.get("LAB_LOG_DIR", "lab-logs")) / request.node.name
            shutil.copytree(instance.dir, target, dirs_exist_ok=True, ignore_dangling_symlinks=True,
                            ignore=shutil.ignore_patterns("wpa"))
        instance.stop_all()


@pytest.fixture
def online(lab):
    """A client that has joined the Wi-Fi network and has an address."""
    lab.lease = lab.go_online()
    return lab
