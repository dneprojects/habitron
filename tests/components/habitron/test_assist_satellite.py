"""Tests for the Habitron assist_satellite platform.

Skeleton — covers smoke-level setup. Extend with per-entity behavior tests
(register/announce/recognize) as the platform stabilizes.
"""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_assist_satellite_setup(setup_integration: MockConfigEntry) -> None:
    """The assist_satellite platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None
