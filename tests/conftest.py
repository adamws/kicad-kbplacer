import base64
import os
import pytest


def to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def svg_to_base64_html(path):
    b64 = to_base64(path)
    return '<div class="image"><img src="data:image/svg+xml;base64,{}"></div>'.format(
        b64
    )


@pytest.mark.hookwrapper
def pytest_runtest_makereport(item, call):
    pytest_html = item.config.pluginmanager.getplugin("html")
    outcome = yield
    report = outcome.get_result()
    extra = getattr(report, "extra", [])

    if report.when == "call":
        tmpdir = item.funcargs["tmpdir"]

        front = svg_to_base64_html(os.path.join(tmpdir, "front.svg"))
        back = svg_to_base64_html(os.path.join(tmpdir, "back.svg"))

        extra.append(pytest_html.extras.html(front))
        extra.append(pytest_html.extras.html(back))

        report.extra = extra
