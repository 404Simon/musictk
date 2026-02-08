"""Playlist synchronization utilities for musictk."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import click

from musictk.mpd import update_mpd_database


# Supported audio file extensions
AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".wav", ".ogg", ".opus", ".aac", ".wma"}


def find_audio_files(directory: Path) -> list[Path]:
    """Find all audio files in a directory (non-recursive).

    Args:
        directory: Directory path to search

    Returns:
        List of audio file paths sorted by name
    """
    audio_files: list[Path] = []
    for item in directory.iterdir():
        if item.is_file() and item.suffix.lower() in AUDIO_EXTENSIONS:
            audio_files.append(item)
    return sorted(audio_files)


def generate_playlist_path(music_folder: Path, playlist_dir: Path) -> tuple[str, Path]:
    """Generate the relative paths needed for m3u playlist.

    Args:
        music_folder: The folder containing music (e.g., ~/Music/Drums+Base)
        playlist_dir: The playlists directory (e.g., ~/Music/mpd/playlists)

    Returns:
        Tuple of (playlist_name, playlist_file_path)
    """
    # Use the folder name as the playlist name
    playlist_name = music_folder.name

    # Playlist file path
    playlist_file = playlist_dir / f"{playlist_name}.m3u"

    return playlist_name, playlist_file


def compute_relative_path(audio_file: Path, playlist_file: Path) -> str:
    """Compute the relative path from playlist file to audio file.

    Args:
        audio_file: Path to the audio file
        playlist_file: Path to the playlist file

    Returns:
        Relative path string for m3u file
    """
    # Get relative path from playlist directory to audio file
    try:
        rel_path = os.path.relpath(audio_file, playlist_file.parent)
        return rel_path
    except ValueError:
        # If on different drives (Windows), use absolute path
        return str(audio_file.resolve())


def create_m3u_content(audio_files: list[Path], playlist_file: Path) -> str:
    """Create m3u playlist content.

    Args:
        audio_files: List of audio file paths
        playlist_file: Path where the playlist will be saved

    Returns:
        M3U playlist content as string
    """
    lines: list[str] = []
    for audio_file in audio_files:
        rel_path = compute_relative_path(audio_file, playlist_file)
        lines.append(rel_path)
    return "\n".join(lines) + "\n" if lines else ""


def sync_playlist(
    music_folder: Path | None = None, playlist_dir: Path | None = None
) -> None:
    """Synchronize a music folder to an m3u playlist.

    Args:
        music_folder: Directory containing music files (default: current directory)
        playlist_dir: Directory for playlists (default: ~/Music/mpd/playlists)
    """
    # Default to current directory if not specified
    if music_folder is None:
        music_folder = Path.cwd()
    else:
        music_folder = music_folder.resolve()

    # Default playlist directory
    if playlist_dir is None:
        playlist_dir = Path.home() / "Music" / "mpd" / "playlists"
    else:
        playlist_dir = playlist_dir.resolve()

    # Validate music folder exists
    if not music_folder.is_dir():
        click.echo(f"Error: {music_folder} is not a directory")
        raise SystemExit(1)

    # Create playlist directory if it doesn't exist
    playlist_dir.mkdir(parents=True, exist_ok=True)

    # Find audio files
    audio_files = find_audio_files(music_folder)

    if not audio_files:
        click.echo(f"No audio files found in {music_folder}")
        return

    # Generate playlist info
    playlist_name, playlist_file = generate_playlist_path(music_folder, playlist_dir)

    # Check if playlist exists
    playlist_exists = playlist_file.exists()

    if not playlist_exists:
        # Ask user if they want to create it
        click.echo(f"Playlist '{playlist_name}' does not exist.")
        if not click.confirm(f"Create new playlist at {playlist_file}?", default=True):
            click.echo("Cancelled")
            return

    # Generate m3u content
    m3u_content = create_m3u_content(audio_files, playlist_file)

    # Write playlist file
    playlist_file.write_text(m3u_content, encoding="utf-8")

    action = "Updated" if playlist_exists else "Created"
    click.echo(f"{action} playlist: {playlist_file}")
    click.echo(f"Added {len(audio_files)} track(s) to '{playlist_name}'")

    # Update MPD database if rmpc is installed
    update_mpd_database()
