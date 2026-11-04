"""Lyrics fetching functionality for audio files."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp
from mutagen._file import File

from musictk.retry import TRANSIENT_HTTP_RETRY

if TYPE_CHECKING:
    from collections.abc import Sequence


class LyricsFetcher:
    API_BASE_URL: str = "https://lrclib.net"
    DEFAULT_REQUEST_INTERVAL: float = 1.0
    RATE_LIMIT_JITTER: float = 0.3
    SUPPORTED_FORMATS: frozenset[str] = frozenset(
        {".mp3", ".flac", ".m4a", ".wav", ".ogg", ".opus"}
    )

    def __init__(
        self,
        base_path: str | Path,
        lyrics_dir: str | Path | None = None,
        request_interval: float = DEFAULT_REQUEST_INTERVAL,
    ) -> None:
        self.base_path = Path(base_path)
        self.lyrics_dir = (
            Path(lyrics_dir) if lyrics_dir else Path.home() / "Music" / "mpd" / "lyrics"
        )
        self.lyrics_dir.mkdir(parents=True, exist_ok=True)
        self.logger = self._setup_logging()
        self.request_interval = max(request_interval, 0.0)
        # lrclib asks clients to send requests sequentially and to space them out,
        # so a single lock serializes all requests instead of allowing bursts.
        self.request_lock = asyncio.Lock()
        self._next_request_at: float = 0.0

    def _setup_logging(self) -> logging.Logger:
        log_dir = self.base_path if self.base_path.is_dir() else self.base_path.parent
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(log_dir / "lyrics_fetcher.log"),
                logging.StreamHandler(),
            ],
        )
        return logging.getLogger(__name__)

    def lrc_paths(self, audio_file_path: Path) -> list[Path]:
        """Return the locations where lyrics for an audio file are stored."""
        lrc_filename = audio_file_path.stem + ".lrc"
        paths = [self.lyrics_dir / lrc_filename, audio_file_path.with_suffix(".lrc")]

        # Deduplicate while preserving order (lyrics dir may be the audio directory)
        unique_paths: list[Path] = []
        for lrc_path in paths:
            if lrc_path not in unique_paths:
                unique_paths.append(lrc_path)
        return unique_paths

    def find_audio_files(self) -> list[Path]:
        audio_files: list[Path] = []

        # If base_path is a file, process just that file
        if self.base_path.is_file():
            if self.base_path.suffix.lower() in self.SUPPORTED_FORMATS:
                if not any(p.exists() for p in self.lrc_paths(self.base_path)):
                    audio_files.append(self.base_path)
                else:
                    self.logger.info(f"LRC already exists for {self.base_path.name}")
            else:
                self.logger.warning(
                    f"File {self.base_path} is not a supported audio format"
                )
        # If base_path is a directory, recursively search for audio files
        elif self.base_path.is_dir():
            for file_path in self.base_path.rglob("*"):
                if (
                    file_path.is_file()
                    and file_path.suffix.lower() in self.SUPPORTED_FORMATS
                ):
                    if not any(p.exists() for p in self.lrc_paths(file_path)):
                        audio_files.append(file_path)
                    else:
                        self.logger.info(f"LRC already exists for {file_path.name}")

        return audio_files

    async def _throttle(self) -> None:
        """Wait for the next request slot to keep requests spaced out.

        Must be called while holding ``request_lock``.
        """
        wait = self._next_request_at - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        self._next_request_at = time.monotonic() + self.request_interval

    @staticmethod
    def _parse_retry_after(value: str | None) -> float | None:
        if value is None:
            return None
        try:
            return max(float(value), 0.0)
        except ValueError:
            return None

    def _retry_delay(self, attempt: int, status: int, retry_after: str | None) -> float:
        if status != 429:
            return TRANSIENT_HTTP_RETRY.delay(attempt, retry_after)

        # lrclib requires Retry-After to be honored in full, not capped by the
        # generic backoff limit, and asks for jitter to avoid synchronized retries.
        parsed_retry_after = self._parse_retry_after(retry_after)
        base_delay = (
            parsed_retry_after
            if parsed_retry_after is not None
            else TRANSIENT_HTTP_RETRY.delay(attempt)
        )
        return base_delay * (1.0 + random.uniform(0.0, self.RATE_LIMIT_JITTER))

    def extract_metadata(self, file_path: Path) -> dict[str, str | int] | None:
        try:
            audio_file = File(file_path)
            if audio_file is None:
                self.logger.warning(f"Could not read metadata from {file_path}")
                return None

            metadata: dict[str, str | int] = {}

            if hasattr(audio_file, "tags") and audio_file.tags:
                tags = audio_file.tags

                title_keys = ["TIT2", "TITLE", "\xa9nam", "Title"]
                for key in title_keys:
                    if key in tags:
                        metadata["title"] = str(tags[key][0])
                        break

                artist_keys = ["TPE1", "ARTIST", "\xa9ART", "Artist"]
                for key in artist_keys:
                    if key in tags:
                        metadata["artist"] = str(tags[key][0])
                        break

                album_keys = ["TALB", "ALBUM", "\xa9alb", "Album"]
                for key in album_keys:
                    if key in tags:
                        metadata["album"] = str(tags[key][0])
                        break

                if hasattr(audio_file, "info") and hasattr(audio_file.info, "length"):
                    metadata["duration"] = int(audio_file.info.length)

            if "title" not in metadata:
                metadata["title"] = file_path.stem

            return metadata

        except Exception as e:
            self.logger.error(f"Error extracting metadata from {file_path}: {e}")
            return None

    async def search_lyrics(
        self, session: aiohttp.ClientSession, metadata: dict[str, str | int]
    ) -> dict[str, str | int] | None:
        params: dict[str, str] = {}

        if "title" in metadata:
            params["track_name"] = str(metadata["title"])
        if "artist" in metadata:
            params["artist_name"] = str(metadata["artist"])
        if "album" in metadata:
            params["album_name"] = str(metadata["album"])

        if not params.get("track_name") and not params.get("artist_name"):
            if "title" in metadata:
                params["q"] = str(metadata["title"])
            else:
                return None

        url = f"{self.API_BASE_URL}/api/search"
        self.logger.info(f"Searching lyrics with params: {params}")
        headers = {"User-Agent": "musictk v0.1.0 (https://github.com/404Simon/musictk)"}

        async with self.request_lock:
            for attempt in range(1, TRANSIENT_HTTP_RETRY.max_attempts + 1):
                await self._throttle()
                try:
                    async with session.get(
                        url,
                        params=params,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as response:
                        if response.status in TRANSIENT_HTTP_RETRY.retryable_statuses:
                            retry_after = response.headers.get("Retry-After")
                            await response.read()
                            if attempt == TRANSIENT_HTTP_RETRY.max_attempts:
                                self.logger.error(
                                    "Lyrics service still unavailable after %d "
                                    "attempts (HTTP %d) for %s",
                                    attempt,
                                    response.status,
                                    params,
                                )
                                return None

                            delay = self._retry_delay(
                                attempt, response.status, retry_after
                            )
                            if response.status == 429:
                                self.logger.warning(
                                    "Lyrics service rate limit hit; retrying in "
                                    "%.1fs (attempt %d/%d)",
                                    delay,
                                    attempt + 1,
                                    TRANSIENT_HTTP_RETRY.max_attempts,
                                )
                            else:
                                self.logger.warning(
                                    "Lyrics service returned HTTP %d; retrying in "
                                    "%.1fs (attempt %d/%d)",
                                    response.status,
                                    delay,
                                    attempt + 1,
                                    TRANSIENT_HTTP_RETRY.max_attempts,
                                )
                        else:
                            response.raise_for_status()
                            results: list[dict[str, str | int]] = await response.json()
                            if results:
                                return results[0]

                            self.logger.warning("No lyrics found")
                            return None

                    await asyncio.sleep(delay)
                except (aiohttp.ClientConnectionError, TimeoutError) as e:
                    if attempt == TRANSIENT_HTTP_RETRY.max_attempts:
                        self.logger.error(
                            "Lyrics request failed after %d attempts: %s", attempt, e
                        )
                        return None

                    delay = TRANSIENT_HTTP_RETRY.delay(attempt)
                    self.logger.warning(
                        "Temporary lyrics request error: %s; retrying in %.1fs "
                        "(attempt %d/%d)",
                        e,
                        delay,
                        attempt + 1,
                        TRANSIENT_HTTP_RETRY.max_attempts,
                    )
                    await asyncio.sleep(delay)
                except aiohttp.ClientError as e:
                    self.logger.error(f"Error searching lyrics: {e}")
                    return None
                except json.JSONDecodeError as e:
                    self.logger.error(f"Error parsing API response: {e}")
                    return None

        return None

    def save_lrc_file(
        self, audio_file_path: Path, lyrics_data: dict[str, str | int]
    ) -> bool:
        try:
            lrc_paths = self.lrc_paths(audio_file_path)

            lyrics_content = lyrics_data.get("syncedLyrics")
            if not lyrics_content:
                lyrics_content = lyrics_data.get("plainLyrics")

            if not lyrics_content:
                self.logger.warning(
                    f"No lyrics content found for {audio_file_path.name}"
                )
                return False

            lines: list[str] = []
            if lyrics_data.get("trackName"):
                lines.append(f"[ti:{lyrics_data['trackName']}]")
            if lyrics_data.get("artistName"):
                lines.append(f"[ar:{lyrics_data['artistName']}]")
            if lyrics_data.get("albumName"):
                lines.append(f"[al:{lyrics_data['albumName']}]")
            if lyrics_data.get("duration"):
                duration = int(lyrics_data["duration"])
                minutes = duration // 60
                seconds = duration % 60
                lines.append(f"[length:{minutes:02d}:{seconds:02d}]")

            lines.append("")
            lines.append(str(lyrics_content))
            content = "\n".join(lines)

            for lrc_path in lrc_paths:
                lrc_path.parent.mkdir(parents=True, exist_ok=True)
                with open(lrc_path, "w", encoding="utf-8") as f:
                    f.write(content)

            written = ", ".join(str(p) for p in lrc_paths)
            self.logger.info(f"Saved lyrics to {written}")
            return True

        except Exception as e:
            self.logger.error(f"Error saving LRC file: {e}")
            return False

    async def process_file(
        self, session: aiohttp.ClientSession, file_path: Path
    ) -> bool:
        self.logger.info(f"Processing: {file_path}")

        metadata = self.extract_metadata(file_path)
        if not metadata:
            self.logger.error(f"Could not extract metadata from {file_path}")
            return False

        lyrics_data = await self.search_lyrics(session, metadata)
        if not lyrics_data:
            self.logger.warning(f"No lyrics found for {file_path.name}")
            return False

        return self.save_lrc_file(file_path, lyrics_data)

    async def run(self) -> None:
        if not self.base_path.exists():
            self.logger.error(f"Path does not exist: {self.base_path}")
            return

        path_type = "file" if self.base_path.is_file() else "directory"
        self.logger.info(f"Starting lyrics fetch for {path_type}: {self.base_path}")

        audio_files = self.find_audio_files()
        if not audio_files:
            self.logger.info("No audio files found that need lyrics")
            return

        self.logger.info(f"Found {len(audio_files)} audio files to process")

        async with aiohttp.ClientSession() as session:
            tasks = [self.process_file(session, file_path) for file_path in audio_files]
            results: Sequence[bool | BaseException] = await asyncio.gather(
                *tasks, return_exceptions=True
            )

        success_count = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"Error processing {audio_files[i]}: {result}")
            elif result:
                success_count += 1

        self.logger.info(
            f"Completed: {success_count}/{len(audio_files)} files "
            f"processed successfully"
        )
