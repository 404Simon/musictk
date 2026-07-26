# 🎵 musictk

**Your all-in-one music toolkit** - Manage audio tags, fetch synced lyrics, and organize your music library with ease.

Built with Python 3.13, strict typing, and modern best practices.

## ✨ Features

### 🎤 Lyrics Fetcher

- Automatically fetch synced (timestamped) lyrics from lrclib.net
- Supports MP3, FLAC, M4A, WAV, OGG, and OPUS formats
- Saves lyrics as LRC files compatible with music players (rmpc, etc.)
- Async processing for lightning-fast execution
- Smart duplicate detection (won't re-fetch existing lyrics)

### 🔍 Similar Track Discovery

- Find similar tracks via the Last.fm API
- Scan current directory for audio files (or search by query text)
- Walks source tracks in directory order, fetching recommendations for
  each, and stops once the requested number of unique results accumulate
- Skips tracks that already exist in the target directory
- Automatically downloads the best YouTube match as Opus via yt-dlp
- Applies ReplayGain (R128_TRACK_GAIN) via ffmpeg loudnorm
- Embeds metadata and sanitizes filenames
- Requires `LASTFM_API_KEY` environment variable (get one at <https://last.fm/api>)

### 📋 Playlist Sync

- Create or update m3u playlist files from music folders
- Relative paths for portable playlists (works across systems)
- Automatic MPD database refresh after sync
- Supports MP3, FLAC, M4A, WAV, OGG, OPUS, AAC, WMA

### 🏷️ Tag Editor

> [!TIP]
> If *Auto Mode* does not get you any results, fill some tags using manual mode first.

**Two powerful modes:**

#### Manual Mode

1. **Extract**: Scans directory for MP3/FLAC/OPUS files and exports all tags to JSON
2. **Edit**: Opens JSON in nvim for bulk editing with full visibility
3. **Apply**: Saves changes back to audio files automatically

#### Auto Mode

1. **Scan**: Finds all audio files and extracts basic metadata
2. **Lookup**: Searches MusicBrainz database for accurate metadata
3. **Download**: Fetches high-quality cover art from Cover Art Archive or iTunes
4. **Apply**: Updates audio files with correct tags and embedded artwork

**Supported Metadata:**

- Basic: Artist, Album, Title, Year, Genre
- Track info: Track number/total, Disc number/total
- Other: Comments, cover art (embedded + separate files)

## 🚀 Installation

```bash
git clone https://github.com/404Simon/musictk
cd musictk
uv sync
```

### Development Setup

```bash
uv sync --extra dev

uv run black musictk/
uv run isort musictk/
uv run mypy musictk/
uv run ruff check musictk/
```

## 📖 Usage

### Lyrics Fetcher

```bash
musictk lyrics ~/Music

musictk lyrics /path/to/album --lyrics-dir /custom/lyrics/path
```

Lyrics are saved to `~/Music/mpd/lyrics/` by default (configurable with `--lyrics-dir`).

### Playlist Sync

```bash
musictk playlist sync

musictk playlist sync --folder ~/Music/Drums+Base

musictk playlist sync -f ~/Music/Jazz -p ~/playlists
```

Creates an `.m3u` playlist named after the folder (e.g. `Drums+Base.m3u`).
If the playlist already exists it is updated silently; otherwise you are
prompted to confirm creation. Playlists are saved to `~/Music/mpd/playlists/`
by default (configurable with `--playlist-dir`/`-p`). After writing, the MPD
database is refreshed automatically via `rmpc update` if available.

### Tag Editor

#### Interactive Mode (Choose at Runtime)

```bash
musictk tags /path/to/music
```

#### Manual Editing Mode

```bash
musictk tags /path/to/music --manual

musictk tags /path/to/music --manual --json /path/to/tags.json
```

#### Automatic Tagging Mode

```bash
musictk tags /path/to/music --auto

musictk tags /path/to/music --auto --no-cover

musictk tags /path/to/music --auto --delay 2.0
```

### Downloader + Search

```bash
musictk download "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

musictk download https://soundcloud.com/monstercat/arcando-pirapus-ultrasound

musictk download "$(wl-paste)"

musictk search griechischer wein

musictk search "arcando california dreamin" --output-dir ~/Music/DNB
```

`search` shows the top 5 YouTube results from `yt-dlp`, lets you pick one interactively,
and then downloads + tags it just like `download`.

For YouTube downloads, sponsor/ad segments (`music_offtopic`, `intro`, `outro`) are removed
and long videos are filtered (`<= 10 minutes`).

### Similar Track Discovery

```bash
export LASTFM_API_KEY="your_key_here"

musictk similar

musictk similar 5

musictk similar "The Weeknd - Blinding Lights"

musictk similar "The Weeknd - Blinding Lights" 5
```

Without any arguments, scans the current directory for audio files and walks them
in filesystem order. For each, it fetches similar tracks from Last.fm and stops
once the requested number (default 3) of unique, non-duplicate results have
accumulated. It then downloads the best YouTube match for each result as Opus,
applies ReplayGain via ffmpeg, embeds metadata, and saves to the current
directory. Tracks already in the directory are automatically skipped.
Temporary files are written to `.similar_tmp/` and cleaned up on completion.

Requires `yt-dlp` and `ffmpeg` to be installed, and `LASTFM_API_KEY` must be set in the environment (get one at <https://last.fm/api>). Only the API key is needed - no secret required.

## 🛠️ Technical Details

- **Python Version**: 3.13+
- **Type Safety**: Fully typed with mypy strict mode
- **Code Quality**: Black, isort, and ruff for formatting and linting
- **Async Support**: asyncio for concurrent operations
- **Dependencies**: click, mutagen, aiohttp, requests

## 🎯 Use Cases

- Organize newly downloaded music with proper metadata
- Bulk edit tags across your entire library
- Add synced lyrics to your music collection
- Fetch missing cover art automatically
- Clean up inconsistent tagging from various sources

## 📝 Requirements

- Python 3.13+
- nvim (for manual tag editing mode)
- yt-dlp (for download/search/similar commands)
- ffmpeg (for ReplayGain in similar command)
- Internet connection (for lyrics fetching, auto-tagging, and similar discovery)
