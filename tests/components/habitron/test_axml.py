"""Tests for the in-tree AXML reader."""

from pathlib import Path

import pytest

from custom_components.habitron._axml import read_apk_version_name

_REAL_APK = (
    Path(__file__).resolve().parents[3]
    / "custom_components"
    / "habitron"
    / "firmware"
    / "sctouch_v1.2.9.apk"
)


@pytest.mark.skipif(
    not _REAL_APK.is_file(),
    reason=(
        "Real APK fixture not present locally — the file is in .gitignore "
        "(190 MB, too large to ship in the repo). Maintainer runs this "
        "test against an APK held outside git; CI exercises the synthetic "
        "fixtures below."
    ),
)
def test_read_apk_version_name_returns_manifest_value() -> None:
    """The real bundled APK reports the versionName it advertises."""
    assert read_apk_version_name(_REAL_APK) == "1.2.9"


def test_read_apk_version_name_missing_file_returns_none(tmp_path: Path) -> None:
    """A non-existent path yields ``None`` instead of raising."""
    assert read_apk_version_name(tmp_path / "does_not_exist.apk") is None


def test_read_apk_version_name_not_a_zip_returns_none(tmp_path: Path) -> None:
    """A file that is not a valid ZIP archive yields ``None``."""
    bogus = tmp_path / "garbage.apk"
    bogus.write_bytes(b"not a zip archive at all")
    assert read_apk_version_name(bogus) is None


def test_read_apk_version_name_zip_without_manifest_returns_none(
    tmp_path: Path,
) -> None:
    """A ZIP that lacks AndroidManifest.xml yields ``None``."""
    import zipfile

    bogus = tmp_path / "empty.apk"
    with zipfile.ZipFile(bogus, "w") as zf:
        zf.writestr("classes.dex", b"")
    assert read_apk_version_name(bogus) is None


def test_read_apk_version_name_corrupted_manifest_returns_none(
    tmp_path: Path,
) -> None:
    """A manifest that isn't valid AXML yields ``None``, not an exception."""
    import zipfile

    bogus = tmp_path / "bad_manifest.apk"
    with zipfile.ZipFile(bogus, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"\x00\x00\x00\x00")
    assert read_apk_version_name(bogus) is None
