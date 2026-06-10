"""Minimal Android binary XML (AXML) reader.

Extracts the ``android:versionName`` attribute from an APK's
``AndroidManifest.xml``. Replaces the ``apkutils`` dependency for the
single operation actually needed by the update platform; nothing else
of the AXML spec is implemented.

Format reference: AOSP ``frameworks/base/include/androidfw/ResourceTypes.h``.
"""

import struct
import zipfile
from pathlib import Path

_RES_XML_TYPE = 0x0003
_CHUNK_STRING_POOL = 0x0001
_CHUNK_XML_START_ELEMENT = 0x0102
_STRING_POOL_FLAG_UTF8 = 1 << 8
_ATTR_TYPE_STRING = 0x03
_NOT_FOUND = 0xFFFFFFFF


def read_apk_version_name(apk_path: Path) -> str | None:
    """Return ``android:versionName`` from an APK, or ``None`` on any failure.

    The function deliberately never raises: a corrupted APK, a missing
    manifest entry, an unexpected AXML layout or a malformed string pool
    all produce ``None`` so the caller (the update entity) can treat them
    uniformly as "version unknown".
    """
    try:
        with zipfile.ZipFile(apk_path) as zf, zf.open("AndroidManifest.xml") as f:
            manifest = f.read()
    except zipfile.BadZipFile, KeyError, OSError:
        return None

    try:
        return _extract_version_name(manifest)
    except struct.error, UnicodeDecodeError, IndexError, ValueError:
        return None


def _extract_version_name(axml: bytes) -> str | None:
    """Walk AXML chunks until the ``<manifest>`` element and read its versionName."""
    file_type, file_hdr, _file_size = struct.unpack_from("<HHI", axml, 0)
    if file_type != _RES_XML_TYPE:
        return None

    strings: list[str] | None = None
    offset = file_hdr

    while offset < len(axml):
        chunk_type, chunk_hdr, chunk_size = struct.unpack_from("<HHI", axml, offset)
        if chunk_size == 0:
            return None
        if chunk_type == _CHUNK_STRING_POOL:
            strings = _parse_string_pool(axml, offset)
        elif chunk_type == _CHUNK_XML_START_ELEMENT and strings is not None:
            version = _read_version_name(axml, offset, chunk_hdr, strings)
            if version is not None:
                return version
        offset += chunk_size

    return None


def _parse_string_pool(data: bytes, offset: int) -> list[str]:
    """Decode the string-pool chunk; return its strings in index order."""
    _ctyp, hdr, _csize, n_str, _n_sty, flags, str_start, _sty_start = (
        struct.unpack_from("<HHIIIIII", data, offset)
    )
    is_utf8 = bool(flags & _STRING_POOL_FLAG_UTF8)
    str_offsets = struct.unpack_from(f"<{n_str}I", data, offset + hdr)
    strings_base = offset + str_start

    strings: list[str] = []
    for rel_off in str_offsets:
        pos = strings_base + rel_off
        if is_utf8:
            # The format stores a u16 length first (for compatibility), then
            # the u8 length. Each can be 1 or 2 bytes depending on a high-bit
            # flag. Only the u8 length is needed to decode.
            pos += 2 if data[pos] & 0x80 else 1
            u8_byte = data[pos]
            if u8_byte & 0x80:
                u8_len = ((u8_byte & 0x7F) << 8) | data[pos + 1]
                pos += 2
            else:
                u8_len = u8_byte
                pos += 1
            strings.append(data[pos : pos + u8_len].decode("utf-8"))
        else:
            u16_len = struct.unpack_from("<H", data, pos)[0]
            if u16_len & 0x8000:
                u16_len = ((u16_len & 0x7FFF) << 16) | struct.unpack_from(
                    "<H", data, pos + 2
                )[0]
                pos += 4
            else:
                pos += 2
            strings.append(data[pos : pos + u16_len * 2].decode("utf-16-le"))

    return strings


def _read_version_name(
    data: bytes, offset: int, hdr_size: int, strings: list[str]
) -> str | None:
    """If the element is ``<manifest>``, return its ``versionName`` attribute."""
    # Element layout after the 16-byte node header:
    #   ns (4) | name (4) | attr_start (2) | attr_size (2) | attr_count (2) | ...
    name_ref = struct.unpack_from("<I", data, offset + 20)[0]
    if _string_at(strings, name_ref) != "manifest":
        return None

    attr_start, attr_size, attr_count = struct.unpack_from(
        "<HHH", data, offset + hdr_size + 8
    )
    attrs_base = offset + hdr_size + attr_start

    for j in range(attr_count):
        a_off = attrs_base + j * attr_size
        _a_ns, a_name, a_raw = struct.unpack_from("<III", data, a_off)
        if _string_at(strings, a_name) != "versionName":
            continue
        # Each attribute carries both a raw string ref and a typed value.
        # The raw ref is the canonical place for string attributes; the
        # typed value is used when the attribute is something other than
        # a string (resource ref, integer, ...).
        if a_raw != _NOT_FOUND:
            return _string_at(strings, a_raw)
        _size, _res0, t_type, t_data = struct.unpack_from("<HBBI", data, a_off + 12)
        if t_type == _ATTR_TYPE_STRING:
            return _string_at(strings, t_data)
        return None

    return None


def _string_at(strings: list[str], idx: int) -> str | None:
    """Safely look up a string by index; return ``None`` for invalid indices."""
    if idx == _NOT_FOUND or idx >= len(strings):
        return None
    return strings[idx]
