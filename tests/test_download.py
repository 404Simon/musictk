from unittest import TestCase
from unittest.mock import Mock, patch

from musictk.download import SearchResult, is_youtube_url, search_youtube


class SearchYouTubeMusicTests(TestCase):
    def test_music_url_is_a_youtube_url(self) -> None:
        self.assertTrue(is_youtube_url("https://music.youtube.com/watch?v=abc123"))

    @patch("ytmusicapi.YTMusic")
    def test_searches_song_catalog(self, ytmusic: Mock) -> None:
        ytmusic.return_value.search.return_value = [
            {
                "resultType": "song",
                "title": "Mondfinsternis",
                "artists": [{"name": "Kollegah"}],
                "duration_seconds": 223,
                "videoId": "abc123",
            }
        ]

        results = search_youtube("Mondfinsternis", max_results=5)

        ytmusic.return_value.search.assert_called_once_with(
            "Mondfinsternis", filter="songs", limit=5
        )
        self.assertEqual(
            results,
            [
                SearchResult(
                    title="Mondfinsternis",
                    artist="Kollegah",
                    duration=223,
                    url="https://music.youtube.com/watch?v=abc123",
                )
            ],
        )

    @patch("ytmusicapi.YTMusic")
    def test_ignores_non_song_and_long_results(self, ytmusic: Mock) -> None:
        ytmusic.return_value.search.return_value = [
            {
                "resultType": "video",
                "title": "Official HD Video",
                "artists": [{"name": "Uploader"}],
                "duration_seconds": 223,
                "videoId": "video",
            },
            {
                "resultType": "song",
                "title": "Ten-hour version",
                "artists": [{"name": "Artist"}],
                "duration_seconds": 36_000,
                "videoId": "long",
            },
        ]

        self.assertEqual(search_youtube("track"), [])
