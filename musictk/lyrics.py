"""Lyrics fetching functionality for audio files."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp
from mutagen._file import File

if TYPE_CHECKING:
    from collections.abc import Sequence


class LyricsFetcher:
    API_BASE_URL: str = "https://lrclib.net"
    SUPPORTED_FORMATS: frozenset[str] = frozenset(
        {".mp3", ".flac", ".m4a", ".wav", ".ogg"}
    )

    def __init__(
        self, base_path: str | Path, lyrics_dir: str | Path | None = None
    ) -> None:
        self.base_path = Path(base_path)
        self.lyrics_dir = (
            Path(lyrics_dir) if lyrics_dir else Path.home() / "Music" / "mpd" / "lyrics"
        )
        self.lyrics_dir.mkdir(parents=True, exist_ok=True)
        self.logger = self._setup_logging()

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

    def find_audio_files(self) -> list[Path]:
        audio_files: list[Path] = []

        # If base_path is a file, process just that file
        if self.base_path.is_file():
            if self.base_path.suffix.lower() in self.SUPPORTED_FORMATS:
                lrc_filename = self.base_path.stem + ".lrc"
                lrc_path = self.lyrics_dir / lrc_filename
                if not lrc_path.exists():
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
                    lrc_filename = file_path.stem + ".lrc"
                    lrc_path = self.lyrics_dir / lrc_filename
                    if not lrc_path.exists():
                        audio_files.append(file_path)
                    else:
                        self.logger.info(f"LRC already exists for {file_path.name}")

        return audio_files

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
        try:
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

            headers = {"User-Agent": "musictk (https://github.com/404Simon/musictk)"}
            async with session.get(
                url,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                response.raise_for_status()
                results: list[dict[str, str | int]] = await response.json()

            if results and isinstance(results, list) and len(results) > 0:
                return results[0]
            else:
                self.logger.warning("No lyrics found")
                return None

        except aiohttp.ClientError as e:
            self.logger.error(f"Error searching lyrics: {e}")
            return None
        except json.JSONDecodeError as e:
            self.logger.error(f"Error parsing API response: {e}")
            return None

    def save_lrc_file(
        self, audio_file_path: Path, lyrics_data: dict[str, str | int]
    ) -> bool:
        try:
            lrc_filename = audio_file_path.stem + ".lrc"
            lrc_path = self.lyrics_dir / lrc_filename

            lyrics_content = lyrics_data.get("syncedLyrics")
            if not lyrics_content:
                lyrics_content = lyrics_data.get("plainLyrics")

            if not lyrics_content:
                self.logger.warning(
                    f"No lyrics content found for {audio_file_path.name}"
                )
                return False

            with open(lrc_path, "w", encoding="utf-8") as f:
                if lyrics_data.get("trackName"):
                    f.write(f"[ti:{lyrics_data['trackName']}]\n")
                if lyrics_data.get("artistName"):
                    f.write(f"[ar:{lyrics_data['artistName']}]\n")
                if lyrics_data.get("albumName"):
                    f.write(f"[al:{lyrics_data['albumName']}]\n")
                if lyrics_data.get("duration"):
                    duration = int(lyrics_data["duration"])
                    minutes = duration // 60
                    seconds = duration % 60
                    f.write(f"[length:{minutes:02d}:{seconds:02d}]\n")

                f.write("\n")
                f.write(str(lyrics_content))

            self.logger.info(f"Saved lyrics to {lrc_path}")
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
