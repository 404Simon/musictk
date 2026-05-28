"""Download and tag music from YouTube and SoundCloud using yt-dlp."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import click
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3
from mutagen.id3._frames import APIC
from mutagen.id3._util import error
from mutagen.mp3 import MP3

from musictk.mpd import update_mpd_database

MAX_DURATION_SECONDS = 10 * 60
YOUTUBE_PREFIXES = (
    "https://www.youtube.com/",
    "https://youtube.com/",
    "https://youtu.be/",
    "https://m.youtube.com/",
    "http://www.youtube.com/",
    "http://youtube.com/",
    "http://youtu.be/",
)


class DownloadError(Exception):
    """Exception raised when download fails."""

    pass


@dataclass(frozen=True)
class SearchResult:
    """Search result returned by yt-dlp."""

    title: str
    artist: str
    duration: int | None
    url: str


class Metadata:
    """Music metadata extracted from yt-dlp."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.title = data.get("title")
        self.artist = data.get("artist") or data.get("uploader")
        self.album = data.get("album")
        self.track = data.get("track")
        self.release_date = data.get("release_date")
        self.thumbnail = data.get("thumbnail")

    @property
    def year(self) -> int | None:
        """Extract year from release_date."""
        if self.release_date and len(self.release_date) >= 4:
            try:
                return int(self.release_date[:4])
            except ValueError:
                return None
        return None


def check_ytdlp() -> bool:
    """Check if yt-dlp is installed and available."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def is_youtube_url(query: str) -> bool:
    """Check if input is a YouTube URL."""
    return query.startswith(YOUTUBE_PREFIXES)


def format_duration(duration: int | None) -> str:
    """Format duration from seconds to mm:ss."""
    if duration is None:
        return "--:--"
    minutes, seconds = divmod(duration, 60)
    return f"{minutes}:{seconds:02d}"


def _metadata_from_search_entry(entry: dict[str, Any]) -> SearchResult | None:
    title_raw = entry.get("title")
    if not title_raw:
        return None

    artist_raw = entry.get("artist") or entry.get("uploader") or "Unknown Artist"
    duration_raw = entry.get("duration")
    duration = int(duration_raw) if isinstance(duration_raw, int | float) else None

    webpage_url = entry.get("webpage_url")
    if not webpage_url:
        video_id = entry.get("id")
        if not video_id:
            return None
        webpage_url = f"https://www.youtube.com/watch?v={video_id}"

    return SearchResult(
        title=str(title_raw),
        artist=str(artist_raw),
        duration=duration,
        url=str(webpage_url),
    )


def search_youtube(query: str, max_results: int = 5) -> list[SearchResult]:
    """Search YouTube with yt-dlp and return top results."""
    click.echo(f"Searching YouTube for: {query}")

    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--dump-json",
                "--flat-playlist",
                "--match-filter",
                f"duration <= {MAX_DURATION_SECONDS}",
                f"ytsearch{max_results}:{query}",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise DownloadError(f"Search failed: {e.stderr.strip()}") from e
    except subprocess.TimeoutExpired as e:
        raise DownloadError("Search timed out") from e

    results: list[SearchResult] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue

        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(entry, dict):
            continue

        parsed = _metadata_from_search_entry(entry)
        if parsed is None:
            continue

        results.append(parsed)

    return results


def choose_result(results: list[SearchResult]) -> SearchResult:
    """Show interactive selection prompt for search results."""
    click.echo()
    click.echo("Top results:")
    for index, result in enumerate(results, start=1):
        duration = format_duration(result.duration)
        click.echo(f"{index}. {result.artist} - {result.title} [{duration}]")

    click.echo()
    while True:
        choice = click.prompt(
            f"Choose track to download (1-{len(results)})",
            type=click.IntRange(1, len(results)),
        )
        if 1 <= choice <= len(results):
            return results[choice - 1]


def extract_metadata(url: str) -> Metadata:
    """Extract metadata from URL using yt-dlp.

    Args:
        url: YouTube or SoundCloud URL

    Returns:
        Metadata object with extracted information

    Raises:
        DownloadError: If metadata extraction fails
    """
    click.echo("Fetching metadata...")

    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-playlist", url],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise DownloadError(f"Failed to extract metadata: {e.stderr}") from e
    except subprocess.TimeoutExpired as e:
        raise DownloadError("Metadata extraction timed out") from e

    try:
        data = json.loads(result.stdout)
        return Metadata(data)
    except json.JSONDecodeError as e:
        raise DownloadError(f"Failed to parse metadata JSON: {e}") from e


def _build_download_args(url: str, output_template: str) -> list[str]:
    args = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "0",
        "--no-playlist",
        "--embed-metadata",
        "--output",
        output_template,
    ]

    if is_youtube_url(url):
        args.extend(
            [
                "--sponsorblock-remove",
                "music_offtopic,intro,outro",
            ]
        )

    args.append(url)
    return args


def download_audio(url: str, output_dir: Path) -> Path:
    """Download audio file as MP3 and return downloaded path."""
    click.echo("Downloading audio...")

    output_template = str(output_dir / "%(title)s [%(id)s].%(ext)s")
    before = set(output_dir.glob("*.mp3"))

    try:
        subprocess.run(
            _build_download_args(url, output_template),
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise DownloadError(f"Download failed: {e.stderr}") from e
    except subprocess.TimeoutExpired as e:
        raise DownloadError("Download timed out") from e

    created = [file for file in output_dir.glob("*.mp3") if file not in before]
    if not created:
        raise DownloadError("Downloaded file not found")

    created.sort(key=lambda file: file.stat().st_mtime, reverse=True)
    return created[0]


def tag_mp3(path: Path, metadata: Metadata) -> None:
    """Add ID3 tags to MP3 file.

    Args:
        path: Path to MP3 file
        metadata: Metadata object with tag information
    """
    click.echo("Tagging audio file...")

    try:
        audio = MP3(path, ID3=EasyID3)
    except error:
        audio = MP3(path)
        audio.add_tags()
        audio = MP3(path, ID3=EasyID3)

    if metadata.title:
        audio["title"] = metadata.title

    if metadata.artist:
        audio["artist"] = metadata.artist

    if metadata.album:
        audio["album"] = metadata.album

    if metadata.year:
        audio["date"] = str(metadata.year)

    audio.save()

    if metadata.thumbnail:
        add_album_art(path, metadata.thumbnail)


def add_album_art(mp3_path: Path, thumbnail_url: str) -> None:
    """Download thumbnail and embed as album art."""
    try:
        click.echo("Downloading album art...")

        with urlopen(thumbnail_url, timeout=30) as response:
            image_data = response.read()

        if image_data.startswith(b"\xff\xd8\xff"):
            mime_type = "image/jpeg"
        elif image_data.startswith(b"\x89PNG"):
            mime_type = "image/png"
        elif image_data.startswith(b"WEBP", 8):
            mime_type = "image/webp"
        else:
            click.echo("Warning: Unknown image format, skipping album art")
            return

        audio = MP3(mp3_path, ID3=ID3)

        if audio.tags is None:
            audio.add_tags()

        tags = audio.tags
        if tags is None:
            click.echo("Warning: Could not initialize ID3 tags")
            return

        tags.add(
            APIC(
                encoding=3,
                mime=mime_type,
                type=3,
                desc="Cover",
                data=image_data,
            )
        )

        audio.save()
        click.echo("Album art embedded successfully")

    except Exception as e:
        click.echo(f"Warning: Could not add album art: {e}")


def download_and_tag(url: str, output_dir: Path) -> Path:
    """Download audio from URL and tag it with metadata."""
    metadata = extract_metadata(url)

    click.echo(f"Title: {metadata.title or 'Unknown'}")
    click.echo(f"Artist: {metadata.artist or 'Unknown'}")
    if metadata.album:
        click.echo(f"Album: {metadata.album}")
    if metadata.year:
        click.echo(f"Year: {metadata.year}")
    click.echo()

    mp3_path = download_audio(url, output_dir)
    tag_mp3(mp3_path, metadata)

    return mp3_path


def run_download(url: str, output_dir: Path | None = None) -> None:
    """Main entry point for download command."""
    if not check_ytdlp():
        click.echo("Error: yt-dlp is not installed or not found in PATH", err=True)
        click.echo("Install it with: pip install yt-dlp", err=True)
        raise click.Abort()

    if output_dir is None:
        output_dir = Path.cwd()

    output_dir.mkdir(parents=True, exist_ok=True)

    click.echo(f"Downloading from: {url}")
    click.echo(f"Output directory: {output_dir}")
    click.echo()

    try:
        mp3_path = download_and_tag(url, output_dir)
        click.echo()
        click.echo(f"Successfully saved to: {mp3_path}")
        update_mpd_database()
    except DownloadError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort() from e
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        raise click.Abort() from e


def run_search_download(query: str, output_dir: Path | None = None) -> None:
    """Search YouTube and download a selected result."""
    if not check_ytdlp():
        click.echo("Error: yt-dlp is not installed or not found in PATH", err=True)
        click.echo("Install it with: pip install yt-dlp", err=True)
        raise click.Abort()

    if output_dir is None:
        output_dir = Path.cwd()

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        results = search_youtube(query, max_results=5)
        if not results:
            raise DownloadError("No suitable results found (duration-filtered)")

        selected = choose_result(results)
        click.echo()
        click.echo(f"Selected: {selected.artist} - {selected.title}")
        click.echo(f"URL: {selected.url}")
        click.echo()

        run_download(selected.url, output_dir)
    except DownloadError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort() from e
