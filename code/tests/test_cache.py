import sys
from pathlib import Path
_code_dir = str(Path(__file__).resolve().parents[1])
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

"""Tests for code/buyorwait/cache.py."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from buyorwait.cache import CacheCorruptionError, CacheKey, ContentAddressedCache, sha256_bytes, sha256_text


def _key(**overrides) -> CacheKey:
    defaults = dict(
        source_id="image_06",
        source_sha256="deadbeef",
        model="gpt-6-astra",
        prompt_version="v1",
        schema_version="v1",
        decoding_config="effort=high",
        tool_contract_version="v1",
    )
    defaults.update(overrides)
    return CacheKey(**defaults)


class BasicRoundTripTests(unittest.TestCase):
    def test_miss_then_set_then_hit(self):
        with TemporaryDirectory() as tmp:
            cache = ContentAddressedCache(tmp)
            k = _key()
            self.assertIsNone(cache.get(k))
            self.assertFalse(cache.has(k))
            cache.set(k, {"total_amount": 1995.0, "currency": "INR"})
            self.assertTrue(cache.has(k))
            self.assertEqual(cache.get(k), {"total_amount": 1995.0, "currency": "INR"})


class CacheInvalidationTests(unittest.TestCase):
    def test_changed_source_bytes_is_a_different_key(self):
        with TemporaryDirectory() as tmp:
            cache = ContentAddressedCache(tmp)
            k1 = _key(source_sha256=sha256_bytes(b"version one"))
            k2 = _key(source_sha256=sha256_bytes(b"version two"))
            cache.set(k1, {"v": 1})
            self.assertIsNone(cache.get(k2))

    def test_changed_model_is_a_different_key(self):
        with TemporaryDirectory() as tmp:
            cache = ContentAddressedCache(tmp)
            cache.set(_key(model="gpt-6-astra"), {"v": 1})
            self.assertIsNone(cache.get(_key(model="gpt-7-nova")))

    def test_changed_schema_version_is_a_different_key(self):
        with TemporaryDirectory() as tmp:
            cache = ContentAddressedCache(tmp)
            cache.set(_key(schema_version="v1"), {"v": 1})
            self.assertIsNone(cache.get(_key(schema_version="v2")))

    def test_changed_decoding_config_is_a_different_key(self):
        with TemporaryDirectory() as tmp:
            cache = ContentAddressedCache(tmp)
            cache.set(_key(decoding_config="effort=low"), {"v": 1})
            self.assertIsNone(cache.get(_key(decoding_config="effort=high")))

    def test_invalidate_removes_entry(self):
        with TemporaryDirectory() as tmp:
            cache = ContentAddressedCache(tmp)
            k = _key()
            cache.set(k, {"v": 1})
            self.assertTrue(cache.invalidate(k))
            self.assertIsNone(cache.get(k))
            self.assertFalse(cache.invalidate(k))  # already gone


class AtomicWriteTests(unittest.TestCase):
    def test_no_temp_files_left_behind_after_a_successful_write(self):
        with TemporaryDirectory() as tmp:
            cache = ContentAddressedCache(tmp)
            cache.set(_key(), {"v": 1})
            leftovers = [p for p in Path(tmp).iterdir() if p.name.startswith(".tmp-")]
            self.assertEqual(leftovers, [])

    def test_reader_never_sees_a_half_written_file(self):
        # Simulate the exact mechanism: write directly to the final path with
        # invalid JSON, confirming a get() on it raises CacheCorruptionError
        # rather than silently returning a partial/garbage value.
        with TemporaryDirectory() as tmp:
            cache = ContentAddressedCache(tmp)
            k = _key()
            path = cache._path(k)
            path.write_text('{"incomplete": tr', encoding="utf-8")
            with self.assertRaises(CacheCorruptionError):
                cache.get(k)
            self.assertTrue(path.with_suffix(path.suffix + ".corrupt").exists())


class RetriableFailedItemsTests(unittest.TestCase):
    def test_absent_entry_after_a_failed_extraction_is_retriable(self):
        # A failed extraction simply never calls .set() -- the next get()
        # is a plain miss, not a poisoned/blocked state.
        with TemporaryDirectory() as tmp:
            cache = ContentAddressedCache(tmp)
            k = _key()
            self.assertIsNone(cache.get(k))  # "failed" = never written
            cache.set(k, {"v": 1})  # a later successful retry writes normally
            self.assertEqual(cache.get(k), {"v": 1})


class TwoLayerSeparationTests(unittest.TestCase):
    def test_observations_and_resolutions_are_independent_stores(self):
        with TemporaryDirectory() as tmp:
            observations = ContentAddressedCache(Path(tmp) / "observations")
            resolutions = ContentAddressedCache(Path(tmp) / "resolutions")
            k = _key()
            observations.set(k, {"layer": "observation"})
            self.assertIsNone(resolutions.get(k))
            resolutions.set(k, {"layer": "resolution"})
            self.assertEqual(observations.get(k), {"layer": "observation"})
            self.assertEqual(resolutions.get(k), {"layer": "resolution"})


class HashHelperTests(unittest.TestCase):
    def test_sha256_bytes_and_text_agree_for_utf8(self):
        self.assertEqual(sha256_bytes("hello".encode("utf-8")), sha256_text("hello"))

    def test_different_content_different_hash(self):
        self.assertNotEqual(sha256_text("a"), sha256_text("b"))


if __name__ == "__main__":
    unittest.main()
