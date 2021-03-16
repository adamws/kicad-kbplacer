import os
import pytest


@pytest.mark.hookwrapper
def pytest_runtest_makereport(item, call):
    pytest_html = item.config.pluginmanager.getplugin("html")
    outcome = yield
    report = outcome.get_result()
    extra = getattr(report, "extra", [])

    if report.when == "call":
        tmpdir = item.funcargs["tmpdir"]
        extra.append(pytest_html.extras.image(os.path.join(tmpdir, "front.png")))
        extra.append(pytest_html.extras.image(os.path.join(tmpdir, "back.png")))
        report.extra = extra
