from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from musictk.retry import RetryPolicy
from musictk.tags import (
    MusicBrainzResult,
    _musicbrainz_query_candidates,
    add_credit_relations,
    enrich_audio_files,
)


def musicbrainz_result() -> MusicBrainzResult:
    return {
        "title": "Track",
        "artist": "Artist",
        "album": "Album",
        "year": "2026",
        "track_num": "1",
        "track_total": "2",
        "genre": "hip hop",
        "mbid": "recording-id",
        "release_mbid": "release-id",
        "producers": [],
        "mixers": [],
        "engineers": [],
    }


class CreditRelationTests(unittest.TestCase):
    def test_adds_supported_credits_without_duplicates(self) -> None:
        result = musicbrainz_result()
        relations = [
            {"type": "producer", "artist": {"name": "Producer"}},
            {"type": "producer", "artist": {"name": "Producer"}},
            {"type": "mix", "artist": {"name": "Mixer"}},
            {"type": "recording", "artist": {"name": "Engineer"}},
            {"type": "mastering", "artist": {"name": "Mastering Engineer"}},
        ]

        add_credit_relations(result, relations)

        self.assertEqual(result["producers"], ["Producer"])
        self.assertEqual(result["mixers"], ["Mixer"])
        self.assertEqual(result["engineers"], ["Engineer", "Mastering Engineer"])

    def test_featured_artist_search_falls_back_to_primary_artist(self) -> None:
        candidates = _musicbrainz_query_candidates("Juju, Tom Hengst", "44 ME")

        self.assertEqual(
            candidates,
            [
                ("Juju, Tom Hengst", "44 ME"),
                ("Juju, Tom Hengst", ""),
                ("Juju", "44 ME"),
                ("Juju", ""),
            ],
        )


class RetryPolicyTests(unittest.TestCase):
    def test_honors_and_bounds_retry_after(self) -> None:
        policy = RetryPolicy(max_delay=30, jitter=0)

        self.assertEqual(policy.delay(1, "12"), 12)
        self.assertEqual(policy.delay(1, "60"), 30)
        self.assertEqual(policy.delay(1, "0"), 2)


class EnrichmentTests(unittest.TestCase):
    @patch("musictk.tags.embed_cover_art", return_value=True)
    @patch("musictk.tags.download_cover_art", return_value=b"cover")
    @patch("musictk.tags.get_cover_art_url", return_value="https://cover")
    @patch("musictk.tags.apply_auto_tags", return_value=True)
    @patch("musictk.tags.search_musicbrainz")
    @patch("musictk.tags.extract_basic_info")
    def test_reuses_cover_download_but_embeds_every_file(
        self,
        extract_info: Mock,
        search: Mock,
        _apply: Mock,
        _cover_url: Mock,
        download_cover: Mock,
        embed_cover: Mock,
    ) -> None:
        extract_info.return_value = {
            "file_path": "track.mp3",
            "artist": "Artist",
            "title": "Track",
            "album": "Album",
            "filename": "track",
        }
        search.return_value = musicbrainz_result()

        summary = enrich_audio_files(
            [Path("01.mp3"), Path("02.mp3")],
            include_cover=True,
            delay=0,
        )

        self.assertEqual(summary.tagged, 2)
        self.assertEqual(summary.covers_embedded, 2)
        download_cover.assert_called_once_with("https://cover")
        self.assertEqual(embed_cover.call_count, 2)


if __name__ == "__main__":
    unittest.main()
