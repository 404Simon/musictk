from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from musictk.lyrics import LyricsFetcher

LYRICS = {"syncedLyrics": "[00:00.00]Hello", "trackName": "Song"}


class SaveLrcFileTests(TestCase):
    def test_saves_lyrics_next_to_audio_file_and_in_lyrics_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            music_dir = root / "music"
            music_dir.mkdir()
            audio_file = music_dir / "song.mp3"
            audio_file.touch()
            lyrics_dir = root / "lyrics"

            fetcher = LyricsFetcher(music_dir, lyrics_dir)

            self.assertTrue(fetcher.save_lrc_file(audio_file, LYRICS))
            self.assertTrue((music_dir / "song.lrc").exists())
            self.assertTrue((lyrics_dir / "song.lrc").exists())
            self.assertEqual(
                (music_dir / "song.lrc").read_text(encoding="utf-8"),
                (lyrics_dir / "song.lrc").read_text(encoding="utf-8"),
            )

    def test_writes_only_once_when_lyrics_dir_is_the_audio_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            music_dir = Path(tmp)
            audio_file = music_dir / "song.mp3"
            audio_file.touch()

            fetcher = LyricsFetcher(music_dir, music_dir)
            self.assertEqual(
                fetcher.lrc_paths(audio_file),
                [music_dir / "song.lrc"],
            )
            self.assertTrue(fetcher.save_lrc_file(audio_file, LYRICS))

    def test_existing_sidecar_skips_audio_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            music_dir = root / "music"
            music_dir.mkdir()
            audio_file = music_dir / "song.mp3"
            audio_file.touch()
            (music_dir / "song.lrc").touch()

            fetcher = LyricsFetcher(music_dir, root / "lyrics")

            self.assertEqual(fetcher.find_audio_files(), [])


class RateLimitTests(TestCase):
    def test_retry_after_is_honored_in_full_for_429(self) -> None:
        with TemporaryDirectory() as tmp:
            fetcher = LyricsFetcher(tmp, request_interval=0)

        delay = fetcher._retry_delay(1, 429, "90")
        self.assertGreaterEqual(delay, 90)
        self.assertLessEqual(delay, 90 * (1 + fetcher.RATE_LIMIT_JITTER))

    def test_429_without_retry_after_falls_back_to_backoff(self) -> None:
        with TemporaryDirectory() as tmp:
            fetcher = LyricsFetcher(tmp, request_interval=0)

        self.assertGreater(fetcher._retry_delay(1, 429, None), 0)
        self.assertGreater(fetcher._retry_delay(1, 429, "not-a-number"), 0)

    def test_request_interval_is_never_negative(self) -> None:
        with TemporaryDirectory() as tmp:
            fetcher = LyricsFetcher(tmp, request_interval=-5)

        self.assertEqual(fetcher.request_interval, 0)
