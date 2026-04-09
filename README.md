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
uv run musictk lyrics ~/Music

uv run musictk lyrics /path/to/album --lyrics-dir /custom/lyrics/path
```

Lyrics are saved to `~/Music/mpd/lyrics/` by default (configurable with `--lyrics-dir`).

### Tag Editor

#### Interactive Mode (Choose at Runtime)

```bash
uv run musictk tags /path/to/music
```

#### Manual Editing Mode

```bash
uv run musictk tags /path/to/music --manual

uv run musictk tags /path/to/music --manual --json /path/to/tags.json
```

#### Automatic Tagging Mode

```bash
uv run musictk tags /path/to/music --auto

uv run musictk tags /path/to/music --auto --no-cover

uv run musictk tags /path/to/music --auto --delay 2.0
```

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
- Internet connection (for lyrics fetching and auto-tagging)
