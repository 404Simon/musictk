"""Last.fm similar track discovery and download for musictk."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, cast

import requests
from mutagen._file import File
from mutagen.oggopus import OggOpus

AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".wav", ".ogg", ".opus"}
MAX_DURATION_SECONDS = 10 * 60


def _get_lastfm_api_key() -> str:
    key = os.environ.get("LASTFM_API_KEY", "")
    if not key:
        print(
            "Error: LASTFM_API_KEY not set.\n"
            "Set it in your shell:  export LASTFM_API_KEY='your_key_here'\n"
            "Get a key at: https://last.fm/api"
        )
        raise SystemExit(1)
    return key


def _lastfm_api_get(params: dict[str, str], api_key: str) -> dict[str, Any]:
    resp = requests.get(
        "https://ws.audioscrobbler.com/2.0/",
        params={**params, "api_key": api_key, "format": "json"},
        timeout=10,
    )
    resp.raise_for_status()
    return cast("dict[str, Any]", resp.json())


def _normalize_artist(artist: str) -> str:
    return artist.strip().lower()


def _normalize_title(title: str) -> str:
    base = title.strip().lower()
    base = base.replace("&", "and")
    base = base.replace("/", " ")
    base = base.replace("_", " ")
    base = re.sub(r"\s+", " ", base)
    base = re.sub(r"\s*\([^)]*\)", "", base)
    base = re.sub(r"\s*\[[^]]*\]", "", base)
    base = re.sub(r"\s*\{[^}]*\}", "", base)
    base = re.sub(
        r"\b(live|remaster(ed)?|remix|version|edit|mix|acoustic|mono|stereo|radio|demo|deluxe|explicit|clean)\b",
        "",
        base,
    )
    base = re.sub(r"\s+", " ", base)
    return base.strip()


def _normalize_track_key(artist: str, title: str) -> str:
    return f"{_normalize_artist(artist)} - {_normalize_title(title)}"


def _clean_track_for_lookup(artist: str, title: str) -> tuple[str, str]:
    cleaned_artist = artist.strip()
    cleaned_title = title.strip()
    if cleaned_artist:
        prefix = f"{cleaned_artist} - "
        if cleaned_title.lower().startswith(prefix.lower()):
            cleaned_title = cleaned_title[len(prefix) :].strip()
    cleaned_title = re.sub(r"\s*[\(\[].*?[\)\]]\s*", " ", cleaned_title)
    cleaned_title = re.sub(r"\s+", " ", cleaned_title).strip()
    return cleaned_artist, cleaned_title


def _coerce_track(
    artist: str | None, title: str | None
) -> tuple[str, str] | None:
    if not artist or not title:
        return None
    cleaned_artist, cleaned_title = _clean_track_for_lookup(artist, title)
    if not cleaned_artist or not cleaned_title:
        return None
    return cleaned_artist, cleaned_title


def _track_lookup_variants(artist: str, title: str) -> list[tuple[str, str]]:
    base_artist, base_title = _clean_track_for_lookup(artist, title)
    variants: list[tuple[str, str]] = [(base_artist, base_title)]

    primary_artist = re.split(
        r"\s*(?:,|&| feat\.?| ft\.?)\s*", base_artist, maxsplit=1
    )[0]
    if primary_artist and primary_artist != base_artist:
        variants.append((primary_artist, base_title))

    stripped_title = re.sub(
        r"\s*[-\u2013\u2014]\s*(feat\.?|ft\.?)\s+.*$",
        "",
        base_title,
        flags=re.IGNORECASE,
    ).strip()
    stripped_title = re.sub(
        r"\s*(feat\.?|ft\.?)\s+.*$", "", stripped_title, flags=re.IGNORECASE
    ).strip()
    if stripped_title and stripped_title != base_title:
        variants.append((base_artist, stripped_title))
        if primary_artist and primary_artist != base_artist:
            variants.append((primary_artist, stripped_title))

    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for variant_artist, variant_title in variants:
        key = _normalize_track_key(variant_artist, variant_title)
        if not variant_artist or not variant_title or key in seen:
            continue
        seen.add(key)
        unique.append((variant_artist, variant_title))
    return unique


def _extract_similar_from_api(
    artist: str, title: str, limit: int, api_key: str
) -> list[tuple[str, str]]:
    try:
        payload = _lastfm_api_get(
            {
                "method": "track.getSimilar",
                "artist": artist,
                "track": title,
                "autocorrect": "1",
                "limit": str(limit),
            },
            api_key,
        )
    except (requests.Timeout, requests.RequestException):
        return []

    tracks = payload.get("similartracks", {}).get("track", [])
    if isinstance(tracks, dict):
        tracks = [tracks]

    results: list[tuple[str, str]] = []
    for entry in tracks:
        if not isinstance(entry, dict):
            continue
        artist_data = entry.get("artist")
        artist_name = ""
        if isinstance(artist_data, dict):
            artist_name = str(artist_data.get("name") or "").strip()
        title_name = str(entry.get("name") or "").strip()
        coerced = _coerce_track(artist_name, title_name)
        if coerced:
            results.append(coerced)
    return results


def _search_tracks_from_api(
    query: str, limit: int, api_key: str
) -> list[tuple[str, str]]:
    try:
        payload = _lastfm_api_get(
            {
                "method": "track.search",
                "track": query,
                "limit": str(limit),
            },
            api_key,
        )
    except (requests.Timeout, requests.RequestException):
        return []

    matches = payload.get("results", {}).get("trackmatches", {}).get("track", [])
    if isinstance(matches, dict):
        matches = [matches]

    results: list[tuple[str, str]] = []
    for entry in matches:
        if not isinstance(entry, dict):
            continue
        artist_name = str(entry.get("artist") or "").strip()
        title_name = str(entry.get("name") or "").strip()
        coerced = _coerce_track(artist_name, title_name)
        if coerced:
            results.append(coerced)
    return results


def _merge_tracks(
    target: list[tuple[str, str]],
    seen: set[str],
    tracks: list[tuple[str, str]],
) -> None:
    for artist, title in tracks:
        key = _normalize_track_key(artist, title)
        if key in seen:
            continue
        seen.add(key)
        target.append((artist, title))


def fetch_similar_tracks(
    artist: str,
    title: str,
    api_key: str,
    limit: int = 3,
) -> list[tuple[str, str]]:
    candidates = _track_lookup_variants(artist, title)
    if not candidates:
        return []

    seen: set[str] = set()
    merged: list[tuple[str, str]] = []
    fetch_limit = max(6, limit * 4)

    for candidate_artist, candidate_title in candidates:
        _merge_tracks(
            merged,
            seen,
            _extract_similar_from_api(
                candidate_artist, candidate_title, fetch_limit, api_key
            ),
        )
        if len(merged) >= limit:
            return merged[:limit]

    search_queries = [
        f"{a} {t}" for a, t in candidates
    ]
    search_queries.extend([t for _, t in candidates])
    for query in search_queries:
        for found_artist, found_title in _search_tracks_from_api(
            query, limit=5, api_key=api_key
        ):
            _merge_tracks(
                merged,
                seen,
                _extract_similar_from_api(
                    found_artist, found_title, fetch_limit, api_key
                ),
            )
            if len(merged) >= limit:
                return merged[:limit]

    return merged[:limit]


def resolve_tracks_from_query(
    query: str, api_key: str, limit: int = 5
) -> list[tuple[str, str]]:
    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    seen: set[str] = set()
    resolved: list[tuple[str, str]] = []
    _merge_tracks(
        resolved,
        seen,
        _search_tracks_from_api(cleaned_query, max(1, min(limit, 50)), api_key),
    )
    return resolved


def fetch_similar_for_query(
    query: str,
    api_key: str,
    limit: int = 3,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    safe_limit = max(1, min(limit, 50))
    source_tracks = resolve_tracks_from_query(query, api_key, limit=5)
    if not source_tracks:
        return [], []

    fetch_limit = max(6, safe_limit * 4)
    seen: set[str] = set()
    merged: list[tuple[str, str]] = []
    for artist, title in source_tracks:
        _merge_tracks(
            merged,
            seen,
            fetch_similar_tracks(artist, title, api_key, fetch_limit),
        )
        if len(merged) >= safe_limit:
            break

    source_keys = {
        _normalize_track_key(artist, title) for artist, title in source_tracks
    }
    filtered = [
        (artist, title)
        for artist, title in merged
        if _normalize_track_key(artist, title) not in source_keys
    ]
    return filtered[:safe_limit], source_tracks


def read_audio_files_metadata(directory: Path) -> list[tuple[str, str]]:
    tracks: list[tuple[str, str]] = []
    for item in directory.iterdir():
        if not item.is_file() or item.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        try:
            audio = File(item)
            if audio is None:
                continue
            title: str | None = None
            artist: str | None = None
            if hasattr(audio, "tags") and audio.tags:
                tags = audio.tags
                title_keys = ["TIT2", "TITLE", "\xa9nam", "Title"]
                for key in title_keys:
                    if key in tags:
                        val = tags[key]
                        title = str(val[0]) if hasattr(val, "__getitem__") else str(val)
                        break
                artist_keys = ["TPE1", "ARTIST", "\xa9ART", "Artist"]
                for key in artist_keys:
                    if key in tags:
                        val = tags[key]
                        artist = (
                            str(val[0])
                            if hasattr(val, "__getitem__")
                            else str(val)
                        )
                        break
            if title and artist:
                tracks.append((artist, title))
        except Exception:
            continue
    return tracks


def _sanitize_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-." else "_" for c in name)


def _resolve_final_path(directory: Path, base_name: str) -> Path:
    final_path = directory / base_name
    counter = 1
    while final_path.exists():
        stem = base_name.rsplit(".", 1)[0]
        final_path = directory / f"{stem}_{counter}.opus"
        counter += 1
    return final_path


def _ytdlp_search_download(query: str, output_template: str) -> dict[str, Any] | None:
    args = [
        "yt-dlp",
        "-x",
        "--audio-format",
        "opus",
        "--audio-quality",
        "5",
        "--embed-metadata",
        "--write-info-json",
        "--print-json",
        "--match-filter",
        f"duration <= {MAX_DURATION_SECONDS}",
        "--sponsorblock-remove",
        "music_offtopic,intro,outro",
        "--output",
        output_template,
        f"ytsearch1:{query}",
    ]
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"  yt-dlp failed: {e.stderr.strip()}")
        return None
    except subprocess.TimeoutExpired:
        print("  yt-dlp timed out")
        return None

    for line in result.stdout.strip().split("\n"):
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict) and "title" in parsed:
                return cast("dict[str, Any]", parsed)
        except json.JSONDecodeError:
            continue
    return None


def _validate_opus(opus_path: Path) -> tuple[bool, str]:
    try:
        audio = OggOpus(str(opus_path))
        duration = audio.info.length if audio.info else 0
        if duration <= 0:
            return False, "Invalid duration (0 seconds)"
        if duration > MAX_DURATION_SECONDS:
            return (
                False,
                f"Duration {duration:.0f}s exceeds max {MAX_DURATION_SECONDS}s",
            )
        return True, f"Valid Opus, duration: {duration:.0f}s"
    except Exception as e:
        return False, f"Opus validation failed: {e}"


def _embed_metadata(opus_path: Path, metadata: dict[str, Any]) -> None:
    try:
        audio = OggOpus(str(opus_path))
        title = metadata.get("title", "")
        artist = metadata.get("artist", "")
        album = metadata.get("album", "")
        if title:
            audio["title"] = title
        if artist:
            audio["artist"] = artist
        if album:
            audio["album"] = album
        audio.save()
    except Exception as e:
        print(f"  Warning: metadata embed failed: {e}")


def _apply_r128_gain(opus_path: Path) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-i", str(opus_path),
                "-af", "loudnorm=print_format=json",
                "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return False, "ffmpeg not available"
    except subprocess.TimeoutExpired:
        return False, "ffmpeg timed out"

    output = (proc.stderr + proc.stdout)
    json_blocks: list[str] = []
    collecting = False
    buffer: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("{"):
            collecting = True
            buffer = [line]
            continue
        if collecting:
            buffer.append(line)
            if stripped.startswith("}"):
                json_blocks.append("\n".join(buffer))
                collecting = False
                buffer = []

    data: dict[str, Any] | None = None
    for block in reversed(json_blocks):
        try:
            data = json.loads(block)
            break
        except json.JSONDecodeError:
            continue

    if not data or "input_i" not in data:
        return False, "Loudness analysis failed"

    try:
        current_lufs = float(data["input_i"])
    except (TypeError, ValueError):
        return False, f"Invalid input_i: {data.get('input_i')}"

    gain_db = -23.0 - current_lufs
    gain_q78 = round(gain_db * 256)

    try:
        audio = OggOpus(str(opus_path))
        audio["R128_TRACK_GAIN"] = str(gain_q78)
        audio.save()
        return True, f"R128_TRACK_GAIN={gain_q78} ({gain_db:.2f} dB)"
    except Exception as e:
        return False, f"Failed to write R128_TRACK_GAIN: {e}"


def run_similar(
    search_text: str | None,
    quantity: int | None,
) -> None:
    api_key = _get_lastfm_api_key()
    limit = quantity if quantity is not None else 3

    if search_text:
        results, source_tracks = fetch_similar_for_query(
            search_text, api_key, limit
        )
        if not source_tracks:
            print("No source tracks found for query.")
            return
        artists_titles = ", ".join(
            f"{a} - {t}" for a, t in source_tracks[:3]
        )
        print(f"Source: {artists_titles}")
    else:
        tracks = read_audio_files_metadata(Path.cwd())
        if not tracks:
            print("No audio files found in current directory.")
            return

        print(f"Found {len(tracks)} track(s) in current directory.")

        existing_tracks = read_audio_files_metadata(Path.cwd())
        existing_keys = {
            _normalize_track_key(a, t) for a, t in existing_tracks
        }
        seen: set[str] = set()
        merged: list[tuple[str, str]] = []
        fetch_limit = max(6, limit * 4)
        consulted = 0

        for artist, title in tracks:
            consulted += 1
            similar = fetch_similar_tracks(artist, title, api_key, fetch_limit)
            for a, t in similar:
                key = _normalize_track_key(a, t)
                if key in seen or key in existing_keys:
                    continue
                seen.add(key)
                merged.append((a, t))
                if len(merged) >= limit:
                    break
            if len(merged) >= limit:
                break

        results = merged[:limit] if merged else []
        if results:
            track_word = "track" if consulted == 1 else "tracks"
            print(
                f"Consulted {consulted} source {track_word}, "
                f"found {len(results)} new."
            )

    if not results:
        print("No new similar tracks found.")
        return

    output_dir = Path.cwd()
    tmp_dir = output_dir / ".similar_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    skipped = 0
    for artist, title in results:
        query = f"{artist} - {title}"
        print(f"\n  {query}")

        tmp_template = str(tmp_dir / "%(title)s.%(ext)s")
        metadata = _ytdlp_search_download(query, tmp_template)
        if not metadata:
            skipped += 1
            continue

        opus_files = list(tmp_dir.glob("*.opus"))
        if not opus_files:
            print("  No opus file produced")
            skipped += 1
            continue

        opus_path = max(opus_files, key=lambda p: p.stat().st_mtime)

        valid, msg = _validate_opus(opus_path)
        if not valid:
            print(f"  Validation failed: {msg}")
            opus_path.unlink(missing_ok=True)
            skipped += 1
            continue

        _embed_metadata(opus_path, metadata)
        gained, gain_msg = _apply_r128_gain(opus_path)

        final_name = _sanitize_filename(f"{artist} - {title}.opus")
        final_path = _resolve_final_path(output_dir, final_name)
        opus_path.rename(final_path)

        lines = [f"  Saved: {final_path.name}"]
        if gained:
            lines.append(f"  Gain: {gain_msg}")
        print("\n".join(lines))
        downloaded += 1

    for leftover in tmp_dir.iterdir():
        leftover.unlink(missing_ok=True)
    tmp_dir.rmdir()

    print()
    print(f"Done. Downloaded: {downloaded}, Skipped: {skipped}")
