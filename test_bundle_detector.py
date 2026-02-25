"""
Unit test for bundle detector. Run before deployment (no Telegram needed).
"""
from bundle_detector import detect_bundle, build_dedup_key

test_files = [
    ("StationX - The Complete Python for Hacking Bundle.zip.001", 3900 * 1024 * 1024),
    ("StationX - The Complete Python for Hacking Bundle.zip.002", 3900 * 1024 * 1024),
    ("StationX - The Complete Python for Hacking Bundle.zip.005", 3299 * 1024 * 1024),
    ("AnotherCourse.zip.001", 3900 * 1024 * 1024),
    ("Course Part 1.zip", 1000 * 1024 * 1024),
    ("Course Part 2.zip", 1000 * 1024 * 1024),
    ("Standalone.zip", 500 * 1024 * 1024),
]

print("=== Bundle Detection Test ===\n")
keys_seen = set()
for filename, size in test_files:
    info = detect_bundle(filename)
    key = build_dedup_key(info, size)
    is_dup = key in keys_seen
    keys_seen.add(key)
    print(f"File: {filename}")
    print(f"  bundle_id:   {info['bundle_id']}")
    print(f"  part_number: {info['part_number']}")
    print(f"  is_part:     {info['is_part']}")
    print(f"  dedup_key:   {key}")
    print(f"  DUPLICATE:   {is_dup}")
    print()

if len(keys_seen) == len(test_files):
    print("PASS: All files have unique dedup keys.")
else:
    print("FAIL: Some keys collided.")
