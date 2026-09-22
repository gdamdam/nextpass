import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import radio_metadata as radio


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        return iter(())

    def read(self):
        return json.dumps(self.payload).encode()


class RadioMetadataTests(unittest.TestCase):
    def fake_opener(self, payload):
        def opener(_request, timeout):
            self.assertEqual(timeout, radio.FETCH_TIMEOUT)
            return Response(payload)
        return opener

    def test_fetch_normalizes_documented_fields_and_marks_catalog_not_live(self):
        with tempfile.TemporaryDirectory() as directory:
            result = radio.load_radio_metadata(
                [57166], Path(directory), opener=self.fake_opener([{
                    "uuid": "tx-1", "norad_cat_id": 57166,
                    "downlink_low": 137900000, "downlink_high": 138000000,
                    "mode": "LRPT", "baud": 72000, "status": "active",
                }]))
            tx = result["satellites"]["57166"][0]
            self.assertEqual(tx["expected_mode"], "LRPT")
            self.assertEqual(tx["protocol"], "unknown")
            self.assertEqual(tx["status_label"], "catalog-status-not-live")
            self.assertEqual(result["license"], "CC BY-SA 4.0")

    def test_band_filter_keeps_overlapping_downlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            result = radio.load_radio_metadata(
                [57166], Path(directory), band="137-138",
                opener=self.fake_opener([{
                    "uuid": "tx-1", "norad_cat_id": 57166,
                    "downlink_low": 137900000, "downlink_high": 137900000,
                }, {
                    "uuid": "tx-2", "norad_cat_id": 57166,
                    "downlink_low": 145800000, "downlink_high": 145800000,
                }]))
            self.assertEqual([row["transmitter_id"] for row in result["satellites"]["57166"]], ["tx-1"])

    def test_malformed_api_has_no_cache_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(radio.RadioMetadataError):
                radio.load_radio_metadata([57166], Path(directory), opener=self.fake_opener({"unexpected": []}))

    def test_fallback_keeps_valid_cache_when_refresh_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            radio.load_radio_metadata([57166], cache, opener=self.fake_opener([{
                "uuid": "tx-1", "norad_cat_id": 57166, "downlink_low": 137900000,
            }]))
            result = radio.load_radio_metadata([57166], cache, refresh=True,
                                               opener=self.fake_opener({"unexpected": []}))
            self.assertEqual(result["satellites"]["57166"][0]["transmitter_id"], "tx-1")

    def test_offline_reads_cache_without_calling_opener(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            radio.load_radio_metadata([57166], cache, opener=self.fake_opener([]))
            def fail(*_args, **_kwargs):
                raise AssertionError("network used in offline mode")
            result = radio.load_radio_metadata([57166], cache, offline=True, opener=fail)
            self.assertEqual(len(result["satellites"]["57166"]), 0)

    def test_local_file_is_offline_and_supports_norad_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "radio.json"
            path.write_text(json.dumps({"57166": [{"frequency_mhz": 137.9, "protocol": "LRPT"}]}))
            def fail(*_args, **_kwargs):
                raise AssertionError("network used for local radio file")
            result = radio.load_radio_metadata([57166], Path(directory), radio_file=path, opener=fail)
            tx = result["satellites"]["57166"][0]
            self.assertEqual(tx["frequency_hz"], 137900000)
            self.assertEqual(result["license"], "user-provided")

    def test_server_response_without_norad_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(radio.RadioMetadataError):
                radio.load_radio_metadata([57166], Path(directory), opener=self.fake_opener([{
                    "uuid": "wrong-filter", "downlink_low": 137900000,
                }]))

    def test_fresh_cache_still_fetches_a_newly_selected_norad(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            radio.load_radio_metadata([57166], cache, opener=self.fake_opener([{
                "uuid": "m2", "norad_cat_id": 57166, "downlink_low": 137900000,
            }]))
            calls = []
            def opener(request, timeout):
                calls.append(request.full_url)
                return Response([{"uuid": "iss", "norad_cat_id": 25544, "downlink_low": 145825000}])
            result = radio.load_radio_metadata([25544], cache, opener=opener)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result["satellites"]["25544"][0]["transmitter_id"], "iss")

    def test_stale_partial_entry_is_retried_without_refreshing_fresh_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            def initial(request, timeout):
                norad = 57166 if "57166" in request.full_url else 59051
                return Response([{"uuid": str(norad), "norad_cat_id": norad, "downlink_low": 137900000}])
            radio.load_radio_metadata([57166, 59051], cache, opener=initial)
            cache_file = cache / radio.RADIO_CACHE_NAME
            payload = json.loads(cache_file.read_text())
            now = datetime.now(timezone.utc).isoformat()
            payload["coverage"]["57166"]["fetched_at_utc"] = "2020-01-01T00:00:00+00:00"
            payload["coverage"]["59051"]["fetched_at_utc"] = now
            cache_file.write_text(json.dumps(payload))
            calls = []
            def failing(request, timeout):
                calls.append(request.full_url)
                raise OSError("temporary outage")
            result = radio.load_radio_metadata([57166, 59051], cache, opener=failing)
            self.assertEqual(len(calls), 1)
            self.assertIn("57166", calls[0])
            self.assertEqual(result["availability"]["57166"]["status"], "available")
            self.assertEqual(result["coverage"]["57166"]["fetched_at_utc"], "2020-01-01T00:00:00+00:00")

    def test_corrupt_coverage_is_not_used(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / radio.RADIO_CACHE_NAME
            path.write_text(json.dumps({"fetched_at_utc": "not-a-date", "coverage": [], "transmitters": []}))
            self.assertIsNone(radio._read_cache(path))


if __name__ == "__main__":
    unittest.main()
