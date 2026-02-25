"""
Bundle-aware deduplication engine (v3.0).
Composite key: (bundle_id, part_number, file_size_bytes).
"""
from bundle_detector import detect_bundle, build_dedup_key
from telegram_handler import get_destination_posts


class BundleDeduplicationEngine:
    """
    Deduplication using composite key: (bundle_id, part_number, file_size_bytes).
    Index loaded from destination channel at startup; updated in-memory as files are processed.
    """

    def __init__(self):
        self._index: set = set()
        self._loaded = False

    async def load(self, bot_client, fetch_limit: int = 500):
        """Loads destination channel history into the dedup index. Call once at startup."""
        print(f"Loading dedup index from destination channel ({fetch_limit} posts)...")
        posts = await get_destination_posts(bot_client, limit=fetch_limit)
        for filename, size in posts:
            bundle_info = detect_bundle(filename)
            key = build_dedup_key(bundle_info, size)
            self._index.add(key)
        self._loaded = True
        print(f"Dedup index loaded: {len(self._index)} entries.")

    def is_duplicate(self, filename: str, file_size_bytes: int) -> bool:
        """Returns True if this file already exists in the destination channel."""
        if not self._loaded:
            raise RuntimeError("Call .load() before using the dedup engine.")
        bundle_info = detect_bundle(filename)
        key = build_dedup_key(bundle_info, file_size_bytes)
        return key in self._index

    def mark_uploaded(self, filename: str, file_size_bytes: int):
        """Adds a newly uploaded file to the in-memory index."""
        bundle_info = detect_bundle(filename)
        key = build_dedup_key(bundle_info, file_size_bytes)
        self._index.add(key)

    def get_bundle_info(self, filename: str) -> dict:
        """Convenience method to get bundle info for a filename."""
        return detect_bundle(filename)
