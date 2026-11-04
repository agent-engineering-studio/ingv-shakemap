from __future__ import annotations

import ingv_shakemap


def test_version_is_exposed() -> None:
    assert ingv_shakemap.__version__
