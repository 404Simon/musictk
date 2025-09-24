import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp
from mutagen._file import File


class LyricsFetcher:

    API_BASE_URL = "https://lrclib.net"
    SUPPORTED_FORMATS = {".mp3", ".flac", ".m4a", ".wav", ".ogg"}

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.lyrics_dir = Path.home() / "Music" / "mpd" / "lyrics"
        self.lyrics_dir.mkdir(parents=True, exist_ok=True)
        self.setup_logging()

    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(self.base_dir / "lyrics_fetcher.log"),
                logging.StreamHandler(),
            ],
        )
        self.logger = logging.getLogger(__name__)

    def find_audio_files(self) -> List[Path]:
        audio_files = []

        for file_path in self.base_dir.rglob("*"):
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

    def extract_metadata(self, file_path: Path) -> Optional[Dict[str, str]]:
        try:
            audio_file = File(file_path)
            if audio_file is None:
                self.logger.warning(f"Could not read metadata from {file_path}")
                return None

            # Common metadata fields across different formats
            metadata = {}

            # Try different tag formats
            if hasattr(audio_file, "tags") and audio_file.tags:
                tags = audio_file.tags

                # Get title
                title_keys = ["TIT2", "TITLE", "\xa9nam", "Title"]
                for key in title_keys:
                    if key in tags:
                        metadata["title"] = str(tags[key][0])
                        break

                # Get artist
                artist_keys = ["TPE1", "ARTIST", "\xa9ART", "Artist"]
                for key in artist_keys:
                    if key in tags:
                        metadata["artist"] = str(tags[key][0])
                        break

                # Get album
                album_keys = ["TALB", "ALBUM", "\xa9alb", "Album"]
                for key in album_keys:
                    if key in tags:
                        metadata["album"] = str(tags[key][0])
                        break

                # Get duration
                if hasattr(audio_file, "info") and hasattr(audio_file.info, "length"):
                    metadata["duration"] = int(audio_file.info.length)

            # Fallback to filename if no title found
            if "title" not in metadata:
                metadata["title"] = file_path.stem

            return metadata

        except Exception as e:
            self.logger.error(f"Error extracting metadata from {file_path}: {e}")
            return None

    async def search_lyrics(
        self, session: aiohttp.ClientSession, metadata: Dict[str, str]
    ) -> Optional[Dict]:
        try:
            params = {}

            if "title" in metadata:
                params["track_name"] = metadata["title"]
            if "artist" in metadata:
                params["artist_name"] = metadata["artist"]
            if "album" in metadata:
                params["album_name"] = metadata["album"]

            # If we don't have track_name or artist, use q parameter for general search
            if not params.get("track_name") and not params.get("artist_name"):
                if "title" in metadata:
                    params["q"] = metadata["title"]
                else:
                    return None

            url = f"{self.API_BASE_URL}/api/search"
            self.logger.info(f"Searching lyrics with params: {params}")

            headers = {
                "User-Agent": "LYRICSFETCHER (https://github.com/404Simon/lyricsfetcher)"
            }
            async with session.get(
                url,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                response.raise_for_status()
                results = await response.json()

            if results and isinstance(results, list) and len(results) > 0:
                # Return the first result (best match)
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

    def save_lrc_file(self, audio_file_path: Path, lyrics_data: Dict) -> bool:
        try:
            lrc_filename = audio_file_path.stem + ".lrc"
            lrc_path = self.lyrics_dir / lrc_filename

            # Prefer synced lyrics, fallback to plain lyrics
            lyrics_content = lyrics_data.get("syncedLyrics")
            if not lyrics_content:
                lyrics_content = lyrics_data.get("plainLyrics")

            if not lyrics_content:
                self.logger.warning(
                    f"No lyrics content found for {audio_file_path.name}"
                )
                return False

            # Write LRC file
            with open(lrc_path, "w", encoding="utf-8") as f:
                # Add metadata to LRC file
                if lyrics_data.get("trackName"):
                    f.write(f"[ti:{lyrics_data['trackName']}]\n")
                if lyrics_data.get("artistName"):
                    f.write(f"[ar:{lyrics_data['artistName']}]\n")
                if lyrics_data.get("albumName"):
                    f.write(f"[al:{lyrics_data['albumName']}]\n")
                if lyrics_data.get("duration"):
                    minutes = int(lyrics_data["duration"] // 60)
                    seconds = int(lyrics_data["duration"] % 60)
                    f.write(f"[length:{minutes:02d}:{seconds:02d}]\n")

                f.write("\n")
                f.write(lyrics_content)

            self.logger.info(f"Saved lyrics to {lrc_path}")
            return True

        except Exception as e:
            self.logger.error(f"Error saving LRC file: {e}")
            return False

    async def process_file(
        self, session: aiohttp.ClientSession, file_path: Path
    ) -> bool:
        self.logger.info(f"Processing: {file_path}")

        # Extract metadata
        metadata = self.extract_metadata(file_path)
        if not metadata:
            self.logger.error(f"Could not extract metadata from {file_path}")
            return False

        # Search for lyrics
        lyrics_data = await self.search_lyrics(session, metadata)
        if not lyrics_data:
            self.logger.warning(f"No lyrics found for {file_path.name}")
            return False

        # Save LRC file
        return self.save_lrc_file(file_path, lyrics_data)

    async def run(self):
        """Main execution function"""
        if not self.base_dir.exists():
            self.logger.error(f"Directory does not exist: {self.base_dir}")
            return

        self.logger.info(f"Starting lyrics fetch for directory: {self.base_dir}")

        audio_files = self.find_audio_files()
        if not audio_files:
            self.logger.info("No audio files found that need lyrics")
            return

        self.logger.info(f"Found {len(audio_files)} audio files to process")

        async with aiohttp.ClientSession() as session:
            tasks = [self.process_file(session, file_path) for file_path in audio_files]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"Error processing {audio_files[i]}: {result}")
            elif result:
                success_count += 1

        self.logger.info(
            f"Completed: {success_count}/{len(audio_files)} files processed successfully"
        )


def main():
    if len(sys.argv) > 1:
        directory = sys.argv[1]
    else:
        directory = str(Path.home() / "Music")

    fetcher = LyricsFetcher(directory)
    asyncio.run(fetcher.run())


if __name__ == "__main__":
    main()
