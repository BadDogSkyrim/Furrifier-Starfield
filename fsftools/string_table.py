"""Read Starfield's localized string tables from the Localization BA2."""
import struct
import zstandard
from pathlib import Path
from typing import Dict, Optional


def load_strings_from_ba2(data_dir: Path, plugin_name: str = 'Starfield',
                          lang: str = 'en') -> Dict[int, str]:
    """Load all .strings entries for a plugin from the Localization BA2.

    Returns {string_id: text}. Covers FULL, SHRT, DESC and similar
    lstring fields.
    """
    ba2_path = data_dir / f'{plugin_name} - Localization.ba2'
    if not ba2_path.exists():
        return {}

    target = f'strings/{plugin_name.lower()}_{lang}.strings'
    data = _extract_from_ba2(ba2_path, target)
    if data is None:
        return {}

    return _parse_strings(data)


def load_all_string_tables(data_dir: Path, plugin_name: str = 'Starfield',
                           lang: str = 'en') -> Dict[int, str]:
    """Load .strings + .dlstrings + .ilstrings, merged into one dict.

    Later entries override earlier ones (IDs are unique within a plugin, not across plugins). Some
    plugins have a Localization archive; DLCs keep their strings in their other archives.
    """
    archives = sorted(data_dir.glob(f'{plugin_name} - *.ba2'),
                      key=lambda p: (not p.name.lower().endswith('localization.ba2'), p.name))
    result = {}
    base = f'strings/{plugin_name.lower()}_{lang}'
    for ext, parser in [('.strings', _parse_strings),
                        ('.dlstrings', _parse_dlstrings),
                        ('.ilstrings', _parse_dlstrings)]:
        for archive in archives:
            data = _extract_from_ba2(archive, base + ext)
            if data:
                result.update(parser(data))
                break
    return result


def _extract_from_ba2(ba2_path: Path, target_name: str) -> Optional[bytes]:
    """Extract one file from a Starfield v2 GNRL BA2."""
    ENTRY_FMT = '<I 4s I I Q I I I'
    ES = struct.calcsize(ENTRY_FMT)  # 36
    HEADER_SIZE = 32  # v2 header: standard 24 + 8 extra

    with open(ba2_path, 'rb') as f:
        f.seek(12)
        file_count = struct.unpack('<I', f.read(4))[0]
        name_table_offset = struct.unpack('<Q', f.read(8))[0]
        f.seek(HEADER_SIZE)

        entries = [struct.unpack(ENTRY_FMT, f.read(ES)) for _ in range(file_count)]

        f.seek(name_table_offset)
        names = []
        for _ in range(file_count):
            nl = struct.unpack('<H', f.read(2))[0]
            names.append(f.read(nl).decode('utf-8'))

        for idx, name in enumerate(names):
            if name.lower() == target_name.lower():
                _, _, _, _, offset, packed, unpacked, _ = entries[idx]
                f.seek(offset)
                raw = f.read(packed if packed else unpacked)
                if packed and packed != unpacked:
                    return zstandard.ZstdDecompressor().decompress(raw, max_output_size=unpacked)
                return raw
    return None


def _parse_strings(data: bytes) -> Dict[int, str]:
    """Parse a .strings file (null-terminated strings)."""
    count = struct.unpack_from('<I', data, 0)[0]
    estart = 8
    dstart = 8 + count * 8
    result = {}
    for j in range(count):
        sid = struct.unpack_from('<I', data, estart + j * 8)[0]
        soff = struct.unpack_from('<I', data, estart + j * 8 + 4)[0]
        end = data.index(b'\x00', dstart + soff)
        result[sid] = data[dstart + soff:end].decode('utf-8', errors='replace')
    return result


def _parse_dlstrings(data: bytes) -> Dict[int, str]:
    """Parse a .dlstrings or .ilstrings file (length-prefixed strings)."""
    count = struct.unpack_from('<I', data, 0)[0]
    estart = 8
    dstart = 8 + count * 8
    result = {}
    for j in range(count):
        sid = struct.unpack_from('<I', data, estart + j * 8)[0]
        soff = struct.unpack_from('<I', data, estart + j * 8 + 4)[0]
        slen = struct.unpack_from('<I', data, dstart + soff)[0]
        result[sid] = data[dstart + soff + 4:dstart + soff + 4 + slen].rstrip(b'\x00').decode('utf-8', errors='replace')
    return result
