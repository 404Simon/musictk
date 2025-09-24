# Lyrics Fetcher

A tool that automatically fetches lyrics for your music library and saves them as LRC files.

## Features

- Scans your music library for audio files (MP3, FLAC, M4A, WAV, OGG)
- Extracts metadata (title, artist, album) from audio files
- Fetches synced lyrics from lrclib.net API
- Saves lyrics as LRC files compatible with music players
- Async processing for faster execution

## Installation

```bash
uv sync
```

## Usage

```bash
# Scan default music directory (~/Music)
uv run main.py

# Scan specific directory
uv run main.py /path/to/your/music
```

Lyrics are saved to `~/Music/mpd/lyrics/` as `.lrc` files matching your audio file names.

## TODO

- save/skip/retry? failed tracks

