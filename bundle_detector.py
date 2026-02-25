"""
Bundle detector for Telegram repost agent (v3.0).
Extracts base_name, part_number, bundle_id from filenames for dedup and Drive organization.
"""
import re
import unicodedata


# Ordered by specificity — most specific patterns first
SERIAL_PATTERNS = [
    # .001, .002, .010, .099  (3-digit numeric extension — most common for zip splits)
    (r'\.(\d{3})$', 'three_digit_ext'),
    # .part1.rar, .part01.rar, .part001.rar
    (r'\.part0*(\d+)\b', 'part_ext'),
    # Part 1, Part 2, Part01, part_2  (word "part" followed by number)
    (r'\bpart[-_\s]*0*(\d+)\b', 'part_word'),
    # Vol 1, Vol. 2, Volume 3, vol1
    (r'\b(?:vol(?:ume)?)[.\s-]*0*(\d+)\b', 'volume_word'),
    # (1), (2), (10)  — parenthesized number at end
    (r'\(0*(\d+)\)\s*$', 'paren_num'),
    # - 1, - 2, _1, _2  at end of name (after stripping extension)
    (r'[-_]\s*0*(\d+)\s*$', 'suffix_num'),
]


def slugify(text: str) -> str:
    """Converts a string to a URL-safe lowercase slug."""
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^\w\s\-]', ' ', text)
    text = re.sub(r'[\s_]+', '-', text.strip())
    return text.lower()[:80]


def split_name_ext(filename: str) -> tuple:
    """
    Splits filename into (name_without_ext, extension).
    Handles compound extensions like .zip.001, .tar.gz.
    Returns (base, ext) where ext may be empty string.
    """
    compound = re.match(r'^(.*?)((?:\.\w+){1,2})$', filename)
    if compound:
        return compound.group(1), compound.group(2).lstrip('.')
    return filename, ''


def detect_bundle(filename: str) -> dict:
    """
    Analyzes a filename and returns structured bundle information.

    Returns a dict:
    {
        'filename':     original filename,
        'base_name':    series name with serial part stripped,
        'part_number':  integer part number (0 if not a series),
        'extension':    file extension(s),
        'is_part':      True if part of a multi-part series,
        'bundle_id':    normalized slug for grouping and Drive subfolder,
        'pattern_type': which pattern matched (for debugging)
    }
    """
    name_lower = filename.lower()

    for pattern, pattern_type in SERIAL_PATTERNS:
        match = re.search(pattern, name_lower, re.IGNORECASE)
        if match:
            part_number = int(match.group(1))
            base_stripped = re.sub(
                pattern, '', filename, flags=re.IGNORECASE
            ).strip(' .-_')
            base_name, extension = split_name_ext(base_stripped)
            if not extension:
                _, extension = split_name_ext(filename.lower())
                extension = re.sub(pattern, '', extension, flags=re.IGNORECASE).strip('.')
            primary_ext = extension.split('.')[0] if extension else ''
            bundle_id = slugify(f"{base_name} {primary_ext}") if primary_ext else slugify(base_name)
            return {
                'filename': filename,
                'base_name': base_name.strip(),
                'part_number': part_number,
                'extension': extension,
                'is_part': True,
                'bundle_id': bundle_id,
                'pattern_type': pattern_type
            }

    base_name, extension = split_name_ext(filename)
    return {
        'filename': filename,
        'base_name': base_name,
        'part_number': 0,
        'extension': extension,
        'is_part': False,
        'bundle_id': slugify(filename),
        'pattern_type': None
    }


def build_dedup_key(bundle_info: dict, file_size_bytes: int) -> tuple:
    """
    Builds the composite deduplication key.
    Format: (bundle_id, part_number, file_size_bytes)
    """
    return (
        bundle_info['bundle_id'],
        bundle_info['part_number'],
        file_size_bytes
    )
