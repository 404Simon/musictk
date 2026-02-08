"""Download and tag music from YouTube and SoundCloud using yt-dlp."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import click
from mutagen.easyid3 import EasyID3
from mutagen.id3 import APIC, ID3, error
from mutagen.mp3 import MP3


class DownloadError(Exception):
    """Exception raised when download fails."""

    pass


class Metadata:
    """Music metadata extracted from yt-dlp."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.title = data.get("title")
        self.artist = data.get("artist") or data.get("uploader")
        self.album = data.get("album")
        self.track = data.get("track")
        self.release_date = data.get("release_date")

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


def download_audio(url: str, output_dir: Path, metadata: Metadata) -> Path:
    """Download audio file as MP3.

    Args:
        url: YouTube or SoundCloud URL
        output_dir: Directory to save the file
        metadata: Metadata object with track information

    Returns:
        Path to downloaded MP3 file

    Raises:
        DownloadError: If download fails
    """
    click.echo("Downloading audio...")

    output_template = str(output_dir / "%(title)s.%(ext)s")

    try:
        subprocess.run(
            [
                "yt-dlp",
                "--extract-audio",
                "--audio-format",
                "mp3",
                "--audio-quality",
                "0",
                "--no-playlist",
                "--output",
                output_template,
                url,
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise DownloadError(f"Download failed: {e.stderr}") from e
    except subprocess.TimeoutExpired as e:
        raise DownloadError("Download timed out") from e

    # Find the downloaded file
    title = metadata.title or "audio"
    mp3_path = output_dir / f"{title}.mp3"

    if not mp3_path.exists():
        raise DownloadError(f"Downloaded file not found at: {mp3_path}")

    return mp3_path


def tag_mp3(path: Path, metadata: Metadata) -> None:
    """Add ID3 tags to MP3 file.

    Args:
        path: Path to MP3 file
        metadata: Metadata object with tag information
    """
    click.echo("Tagging audio file...")

    try:
        # Use EasyID3 for simple tags
        audio = MP3(path, ID3=EasyID3)
    except error:
        # Create new ID3 tag if none exists
        audio = MP3(path)
        audio.add_tags()
        audio = MP3(path, ID3=EasyID3)

    # Set basic tags
    if metadata.title:
        audio["title"] = metadata.title

    if metadata.artist:
        audio["artist"] = metadata.artist

    if metadata.album:
        audio["album"] = metadata.album

    if metadata.year:
        audio["date"] = str(metadata.year)

    audio.save()


def download_and_tag(url: str, output_dir: Path) -> Path:
    """Download audio from URL and tag it with metadata.

    Args:
        url: YouTube or SoundCloud URL
        output_dir: Directory to save the file

    Returns:
        Path to downloaded and tagged MP3 file

    Raises:
        DownloadError: If download or tagging fails
    """
    # Extract metadata
    metadata = extract_metadata(url)

    click.echo(f"Title: {metadata.title or 'Unknown'}")
    click.echo(f"Artist: {metadata.artist or 'Unknown'}")
    if metadata.album:
        click.echo(f"Album: {metadata.album}")
    if metadata.year:
        click.echo(f"Year: {metadata.year}")
    click.echo()

    # Download audio
    mp3_path = download_audio(url, output_dir, metadata)

    # Tag the file
    tag_mp3(mp3_path, metadata)

    return mp3_path


def run_download(url: str, output_dir: Path | None = None) -> None:
    """Main entry point for download command.

    Args:
        url: YouTube or SoundCloud URL
        output_dir: Optional output directory (defaults to current directory)
    """
    # Check if yt-dlp is installed
    if not check_ytdlp():
        click.echo("Error: yt-dlp is not installed or not found in PATH", err=True)
        click.echo("Install it with: pip install yt-dlp", err=True)
        raise click.Abort()

    # Use current directory if not specified
    if output_dir is None:
        output_dir = Path.cwd()

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    click.echo(f"Downloading from: {url}")
    click.echo(f"Output directory: {output_dir}")
    click.echo()

    try:
        mp3_path = download_and_tag(url, output_dir)
        click.echo()
        click.echo(f"Successfully saved to: {mp3_path}")
    except DownloadError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        raise click.Abort()
