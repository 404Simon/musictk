"""CLI entry point for musictk."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from musictk.lyrics import LyricsFetcher
from musictk.tags import auto_tag_mode, manual_edit_mode


@click.group()
@click.version_option(version="0.1.0", prog_name="musictk")
def main() -> None:
    """musictk - Your all-in-one music toolkit.

    Manage audio tags, fetch lyrics, and organize your music library.
    """
    pass


@main.command()
@click.argument("directory", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--lyrics-dir",
    type=click.Path(path_type=Path),
    help="Custom directory for lyrics files (default: ~/Music/mpd/lyrics)",
)
def lyrics(directory: Path, lyrics_dir: Path | None) -> None:
    """Fetch synced lyrics for your music library.

    Scans DIRECTORY for audio files and downloads synced lyrics from lrclib.net.
    Supports MP3, FLAC, M4A, WAV, and OGG files.

    Examples:
      musictk lyrics ~/Music
      musictk lyrics /path/to/album --lyrics-dir /custom/lyrics/path
    """
    fetcher = LyricsFetcher(directory, lyrics_dir)
    asyncio.run(fetcher.run())


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--auto", is_flag=True, help="Automatic tagging mode")
@click.option("--manual", is_flag=True, help="Manual editing mode")
@click.option(
    "--no-cover", is_flag=True, help="Skip cover art download (auto mode only)"
)
@click.option(
    "--delay",
    type=float,
    default=1.0,
    help="Delay between requests in seconds (auto mode only)",
)
@click.option(
    "--json",
    "json_path",
    type=click.Path(path_type=Path),
    help="JSON file path for manual mode (default: directory/tags.json)",
)
def tags(
    path: Path,
    auto: bool,
    manual: bool,
    no_cover: bool,
    delay: float,
    json_path: Path | None,
) -> None:
    """Edit audio tags manually or automatically.

    Two modes available:
    - Manual: Extract tags to JSON, edit in nvim, apply changes
    - Auto: Lookup metadata from MusicBrainz and download cover art

    Examples:
      musictk tags ~/Music --auto
      musictk tags ~/Music/song.mp3 --auto
      musictk tags ~/Music --manual
      musictk tags ~/Music --auto --no-cover
      musictk tags ~/Music --manual --json custom_tags.json
    """
    path = path.resolve()

    if not path.exists():
        click.echo(f"Error: Path not found: {path}")
        sys.exit(1)

    if auto and manual:
        click.echo("Error: Cannot specify both --auto and --manual")
        sys.exit(1)
    elif auto:
        mode = "auto"
    elif manual:
        mode = "manual"
    else:
        click.echo("musictk - Audio Tag Editor")
        click.echo("==========================")
        click.echo("Choose tagging mode:")
        click.echo("1. Manual editing (extract tags → edit in nvim → apply changes)")
        click.echo("2. Automatic tagging (lookup metadata and cover art online)")
        click.echo()

        while True:
            try:
                choice = click.prompt("Enter choice (1 or 2)", type=str).strip()
                if choice == "1":
                    mode = "manual"
                    break
                elif choice == "2":
                    mode = "auto"
                    break
                else:
                    click.echo("Please enter 1 or 2")
            except click.Abort:
                click.echo("\nCancelled")
                sys.exit(0)

    if mode == "manual":
        if path.is_file():
            final_json_path = json_path or path.parent / "tags.json"
        else:
            final_json_path = json_path or path / "tags.json"
        manual_edit_mode(str(path), str(final_json_path))
    elif mode == "auto":
        if json_path:
            click.echo("Warning: --json option is ignored in auto mode")
        auto_tag_mode(str(path), no_cover, delay)


if __name__ == "__main__":
    main()
