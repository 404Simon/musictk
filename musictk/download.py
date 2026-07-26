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


@dataclass(frozen=True)
class AlbumResult:
    """Album search result from YouTube Music."""

    title: str
    artist: str
    year: str | None
    browse_id: str
    playlist_id: str | None


@dataclass(frozen=True)
class AlbumTrack:
    """A track within a YouTube Music album."""

    title: str
    artist: str
    duration_seconds: int
    track_number: int
    video_id: str


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
        choice: int = click.prompt(
            f"Choose track to download (1-{len(results)})",
            type=click.IntRange(1, len(results)),
        )
        if 1 <= choice <= len(results):
            return results[choice - 1]


def _get_artist_name(entry: dict[str, Any]) -> str | None:
    """Extract artist name from a ytmusicapi result entry.

    Handles both 'artist' (str) and 'artists' (list[dict]) fields.
    """
    artist = entry.get("artist")
    if isinstance(artist, str):
        return artist

    artists = entry.get("artists")
    if isinstance(artists, list) and len(artists) > 0:
        name: object = artists[0].get("name")
        if isinstance(name, str):
            return name

    return None


def search_albums(query: str, max_results: int = 5) -> list[AlbumResult]:
    """Search YouTube Music for albums using ytmusicapi."""
    click.echo(f"Searching YouTube Music for: {query}")

    try:
        from ytmusicapi import YTMusic

        yt = YTMusic()
        raw = yt.search(query, filter="albums", limit=max_results)
    except Exception as e:
        raise DownloadError(f"Album search failed: {e}") from e

    results: list[AlbumResult] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if entry.get("resultType") != "album":
            continue

        title = entry.get("title")
        artist = _get_artist_name(entry)
        if not title or not artist:
            continue

        results.append(
            AlbumResult(
                title=str(title),
                artist=str(artist),
                year=str(entry["year"]) if entry.get("year") else None,
                browse_id=str(entry["browseId"]),
                playlist_id=(
                    str(entry["playlistId"]) if entry.get("playlistId") else None
                ),
            )
        )

    return results


def get_album_details(
    result: AlbumResult,
) -> tuple[str, str, str, str | None, list[AlbumTrack]]:
    """Get full album details including track list.

    Returns: (album_title, artist, playlist_url, thumbnail_url, tracks)
    """
    from ytmusicapi import YTMusic

    yt = YTMusic()
    data = yt.get_album(result.browse_id)

    title = str(data.get("title", result.title))

    artist: str = result.artist
    artists = data.get("artists")
    if artists and isinstance(artists, list) and len(artists) > 0:
        artist = str(artists[0].get("name", result.artist))

    audio_playlist_id = data.get("audioPlaylistId")
    if audio_playlist_id:
        playlist_url = f"https://music.youtube.com/playlist?list={audio_playlist_id}"
    elif result.playlist_id:
        playlist_url = f"https://music.youtube.com/playlist?list={result.playlist_id}"
    else:
        playlist_url = f"https://music.youtube.com/browse/VL{result.browse_id}"

    thumbnail_url: str | None = None
    raw_thumbnails = data.get("thumbnails")
    if raw_thumbnails and isinstance(raw_thumbnails, list) and len(raw_thumbnails) > 0:
        thumb = raw_thumbnails[-1]
        if isinstance(thumb, dict):
            url = thumb.get("url")
            if url and isinstance(url, str):
                thumbnail_url = url

    tracks_raw = data.get("tracks", [])
    tracks: list[AlbumTrack] = []
    for t in tracks_raw:
        if not isinstance(t, dict):
            continue
        track_title = t.get("title")
        if not track_title:
            continue

        track_artist: str = artist
        t_artists = t.get("artists")
        if t_artists and isinstance(t_artists, list) and len(t_artists) > 0:
            track_artist = str(t_artists[0].get("name", artist))

        tracks.append(
            AlbumTrack(
                title=str(track_title),
                artist=track_artist,
                duration_seconds=int(t.get("duration_seconds", 0) or 0),
                track_number=int(t.get("trackNumber", 0)),
                video_id=str(t.get("videoId", "")),
            )
        )

    return title, artist, playlist_url, thumbnail_url, tracks


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


def _build_download_args(
    url: str, output_template: str, no_playlist: bool = True
) -> list[str]:
    args = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "0",
        "--embed-metadata",
        "--output",
        output_template,
    ]

    if no_playlist:
        args.append("--no-playlist")

    if is_youtube_url(url):
        args.extend(
            [
                "--sponsorblock-remove",
                "music_offtopic,intro,outro",
            ]
        )

    args.append(url)
    return args


def download_album(album_url: str, output_dir: Path) -> list[Path]:
    """Download all tracks in an album and return list of created MP3 paths."""
    output_template = str(
        output_dir
        / "%(album_artist,uploader)s - %(album,playlist_title)s"
        / "%(playlist_index)02d - %(title)s.%(ext)s"
    )

    before = set(output_dir.rglob("*.mp3"))

    try:
        subprocess.run(
            _build_download_args(album_url, output_template, no_playlist=False),
            timeout=600,
            check=True,
        )
    except subprocess.CalledProcessError:
        raise DownloadError("Album download failed") from None
    except subprocess.TimeoutExpired as e:
        raise DownloadError("Album download timed out") from e

    created = [f for f in output_dir.rglob("*.mp3") if f not in before]
    if not created:
        raise DownloadError("No files were downloaded")

    created.sort(key=lambda f: f.stat().st_mtime)
    return created


def download_audio(url: str, output_dir: Path) -> Path:
    """Download audio file as MP3 and return downloaded path."""
    click.echo("Downloading audio...")

    output_template = str(output_dir / "%(title)s.%(ext)s")
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


def _show_playlist_tracks(url: str) -> tuple[str, list[dict[str, Any]]]:
    """Fetch and display playlist/album track listing.

    Returns: (playlist_title, list_of_track_dicts_from_ytdlp)
    """
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--flat-playlist", url],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise DownloadError(f"Failed to get playlist info: {e.stderr}") from e

    tracks: list[dict[str, Any]] = []
    playlist_title: str = "Unknown Album"
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        playlist_title = entry.get("playlist_title") or playlist_title
        tracks.append(entry)

    click.echo(f"Album: {playlist_title}")
    click.echo(f"Tracks: {len(tracks)}")
    click.echo()

    for i, track in enumerate(tracks, start=1):
        title = track.get("title", "Unknown")
        raw_dur = track.get("duration")
        dur = int(raw_dur) if isinstance(raw_dur, int | float) else None
        click.echo(f"  {i:2d}. {title} [{format_duration(dur)}]")

    return playlist_title, tracks


def run_download(
    url: str, output_dir: Path | None = None, album: bool = False
) -> None:
    """Main entry point for download command."""
    if not check_ytdlp():
        click.echo("Error: yt-dlp is not installed or not found in PATH", err=True)
        click.echo("Install it with: pip install yt-dlp", err=True)
        raise click.Abort()

    if output_dir is None:
        output_dir = Path.cwd()

    output_dir.mkdir(parents=True, exist_ok=True)

    if album:
        click.echo(f"Downloading album from: {url}")
        click.echo(f"Output directory: {output_dir}")
        click.echo()

        try:
            _show_playlist_tracks(url)
            click.echo()
            click.confirm("Download this album?", default=True, abort=True)
            click.echo()

            paths = download_album(url, output_dir)
            click.echo(f"Downloaded {len(paths)} tracks")

            meta = extract_metadata(url)
            if meta.thumbnail:
                click.echo("Embedding album art...")
                for p in paths:
                    add_album_art(p, meta.thumbnail)

            update_mpd_database()
        except DownloadError as e:
            click.echo(f"Error: {e}", err=True)
            raise click.Abort() from e
        except Exception as e:
            click.echo(f"Unexpected error: {e}", err=True)
            raise click.Abort() from e
    else:
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


def run_search_download(
    query: str, output_dir: Path | None = None, album: bool = False
) -> None:
    """Search YouTube and download a selected result."""
    if not check_ytdlp():
        click.echo("Error: yt-dlp is not installed or not found in PATH", err=True)
        click.echo("Install it with: pip install yt-dlp", err=True)
        raise click.Abort()

    if output_dir is None:
        output_dir = Path.cwd()

    output_dir.mkdir(parents=True, exist_ok=True)

    if album:
        try:
            album_results = search_albums(query)
        except DownloadError as e:
            click.echo(f"Error: {e}", err=True)
            raise click.Abort() from e

        if not album_results:
            click.echo("No albums found.")
            raise click.Abort()

        click.echo(f"Found {len(album_results)} albums:")
        for i, alb in enumerate(album_results, start=1):
            year_str = f" ({alb.year})" if alb.year else ""
            click.echo(f"  {i}. {alb.artist} - {alb.title}{year_str}")

        click.echo()
        album_choice = click.prompt(
            f"Choose album to download (1-{len(album_results)})",
            type=click.IntRange(1, len(album_results)),
        )
        selected_album = album_results[album_choice - 1]

        click.echo()
        click.echo("Fetching album details...")
        try:
            album_title, artist, playlist_url, album_thumbnail, tracks = (
                get_album_details(selected_album)
            )
        except Exception as e:
            click.echo(f"Error: Failed to get album details: {e}", err=True)
            raise click.Abort() from e

        click.echo()
        click.echo(f"  {artist} - {album_title}")
        click.echo(f"  Tracks: {len(tracks)}")
        click.echo()
        for track in tracks:
            click.echo(
                f"    {track.track_number:2d}. {track.title}"
                f" [{format_duration(track.duration_seconds)}]"
            )

        click.echo()
        click.confirm("Download this album?", default=True, abort=True)
        click.echo()

        try:
            paths = download_album(playlist_url, output_dir)
            click.echo(f"Downloaded {len(paths)} tracks")

            if album_thumbnail:
                click.echo("Embedding album art...")
                for p in paths:
                    add_album_art(p, album_thumbnail)

            update_mpd_database()
        except DownloadError as e:
            click.echo(f"Error: {e}", err=True)
            raise click.Abort() from e
        except Exception as e:
            click.echo(f"Unexpected error: {e}", err=True)
            raise click.Abort() from e
    else:
        try:
            search_results = search_youtube(query, max_results=5)
            if not search_results:
                raise DownloadError("No suitable results found (duration-filtered)")

            selected = choose_result(search_results)
            click.echo()
            click.echo(f"Selected: {selected.artist} - {selected.title}")
            click.echo(f"URL: {selected.url}")
            click.echo()

            run_download(selected.url, output_dir)
        except DownloadError as e:
            click.echo(f"Error: {e}", err=True)
            raise click.Abort() from e
