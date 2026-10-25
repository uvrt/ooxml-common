"""``--update-goldens``: rewrite ``tests/golden/`` from what the package produces now
(``tests/goldens.py``)."""


def pytest_addoption(parser):
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="rewrite tests/golden/ from this checkout's output; those tests skip instead of passing",
    )
