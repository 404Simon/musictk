"""Audio tag editing functionality."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict
from urllib.parse import quote

import click
import requests
from mutagen._file import File as MutagenFile
from mutagen.flac import FLAC, Picture
from mutagen.id3._frames import APIC, COMM, TALB, TCON, TDRC, TIT2, TPE1, TPOS, TRCK
from mutagen.mp3 import MP3

if TYPE_CHECKING:
    from collections.abc import Sequence


class AudioTags(TypedDict):
    file_path: str
    artist: str
    album: str
    title: str
    track_num: str
    track_total: str
    disc_num: str
    disc_total: str
    year: str
    genre: str
    comment: str


class BasicInfo(TypedDict):
    file_path: str
    artist: str
    title: str
    album: str
    filename: str


class MusicBrainzResult(TypedDict):
    title: str
    artist: str
    album: str
    year: str
    track_num: str
    track_total: str
    genre: str
    mbid: str


def get_audio_files(path: str | Path) -> list[str]:
    file_path = Path(path)

    if file_path.is_file():
        if file_path.suffix.lower() in (".mp3", ".flac"):
            return [str(file_path)]
        else:
            return []

    audio_files: list[str] = []
    for f in file_path.rglob("*"):
        if f.is_file() and f.suffix.lower() in (".mp3", ".flac"):
            audio_files.append(str(f))

    return sorted(audio_files)


def extract_tags(file_path: str) -> AudioTags | None:
    try:
        audio_file = MutagenFile(file_path)

        if audio_file is None:
            print(f"Warning: Could not read tags from {file_path}")
            return None

        tags: AudioTags = {
            "file_path": file_path,
            "artist": "",
            "album": "",
            "title": "",
            "track_num": "",
            "track_total": "",
            "disc_num": "",
            "disc_total": "",
            "year": "",
            "genre": "",
            "comment": "",
        }

        if isinstance(audio_file, MP3):
            tpe1 = audio_file.get("TPE1")
            tags["artist"] = str(tpe1[0]) if tpe1 else ""
            talb = audio_file.get("TALB")
            tags["album"] = str(talb[0]) if talb else ""
            tit2 = audio_file.get("TIT2")
            tags["title"] = str(tit2[0]) if tit2 else ""
            tdrc = audio_file.get("TDRC")
            tags["year"] = str(tdrc[0]) if tdrc else ""
            tcon = audio_file.get("TCON")
            tags["genre"] = str(tcon[0]) if tcon else ""

            trck = audio_file.get("TRCK")
            track_info = str(trck[0]) if trck else ""
            if "/" in track_info:
                track_parts = track_info.split("/")
                tags["track_num"] = track_parts[0]
                tags["track_total"] = track_parts[1] if len(track_parts) > 1 else ""
            else:
                tags["track_num"] = track_info

            tpos = audio_file.get("TPOS")
            disc_info = str(tpos[0]) if tpos else ""
            if "/" in disc_info:
                disc_parts = disc_info.split("/")
                tags["disc_num"] = disc_parts[0]
                tags["disc_total"] = disc_parts[1] if len(disc_parts) > 1 else ""
            else:
                tags["disc_num"] = disc_info

            comm_frames = audio_file.get("COMM::eng")
            if comm_frames:
                tags["comment"] = str(comm_frames)

        elif isinstance(audio_file, FLAC):
            artist_tag = audio_file.get("ARTIST")
            tags["artist"] = str(artist_tag[0]) if artist_tag else ""
            album_tag = audio_file.get("ALBUM")
            tags["album"] = str(album_tag[0]) if album_tag else ""
            title_tag = audio_file.get("TITLE")
            tags["title"] = str(title_tag[0]) if title_tag else ""
            date_tag = audio_file.get("DATE")
            tags["year"] = str(date_tag[0]) if date_tag else ""
            genre_tag = audio_file.get("GENRE")
            tags["genre"] = str(genre_tag[0]) if genre_tag else ""
            tracknum_tag = audio_file.get("TRACKNUMBER")
            tags["track_num"] = str(tracknum_tag[0]) if tracknum_tag else ""
            tracktotal_tag = audio_file.get("TRACKTOTAL")
            tags["track_total"] = str(tracktotal_tag[0]) if tracktotal_tag else ""
            discnum_tag = audio_file.get("DISCNUMBER")
            tags["disc_num"] = str(discnum_tag[0]) if discnum_tag else ""
            disctotal_tag = audio_file.get("DISCTOTAL")
            tags["disc_total"] = str(disctotal_tag[0]) if disctotal_tag else ""
            comment_tag = audio_file.get("COMMENT")
            tags["comment"] = str(comment_tag[0]) if comment_tag else ""

        tags["artist"] = str(tags["artist"]).strip() if tags["artist"] else ""
        tags["album"] = str(tags["album"]).strip() if tags["album"] else ""
        tags["title"] = str(tags["title"]).strip() if tags["title"] else ""
        tags["track_num"] = str(tags["track_num"]).strip() if tags["track_num"] else ""
        tags["track_total"] = (
            str(tags["track_total"]).strip() if tags["track_total"] else ""
        )
        tags["disc_num"] = str(tags["disc_num"]).strip() if tags["disc_num"] else ""
        tags["disc_total"] = (
            str(tags["disc_total"]).strip() if tags["disc_total"] else ""
        )
        tags["year"] = str(tags["year"]).strip() if tags["year"] else ""
        tags["genre"] = str(tags["genre"]).strip() if tags["genre"] else ""
        tags["comment"] = str(tags["comment"]).strip() if tags["comment"] else ""

        return tags

    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return None


def write_json(tags_list: Sequence[AudioTags], json_path: str) -> None:
    if not tags_list:
        print("No tags to write")
        return

    with open(json_path, "w", encoding="utf-8") as jsonfile:
        json.dump(tags_list, jsonfile, indent=2, ensure_ascii=False)


def read_json(json_path: str) -> list[Any]:
    with open(json_path, encoding="utf-8") as jsonfile:
        return list(json.load(jsonfile))


def apply_tags(tags: dict[str, Any]) -> bool:
    file_path = tags["file_path"]

    if not os.path.exists(file_path):
        print(f"Warning: File not found: {file_path}")
        return False

    try:
        audio_file = MutagenFile(file_path)

        if audio_file is None:
            print(f"Warning: Could not open {file_path}")
            return False

        if isinstance(audio_file, MP3):
            if tags.get("artist"):
                audio_file["TPE1"] = TPE1(encoding=3, text=[tags["artist"]])
            if tags.get("album"):
                audio_file["TALB"] = TALB(encoding=3, text=[tags["album"]])
            if tags.get("title"):
                audio_file["TIT2"] = TIT2(encoding=3, text=[tags["title"]])
            if tags.get("year"):
                audio_file["TDRC"] = TDRC(encoding=3, text=[tags["year"]])
            if tags.get("genre"):
                audio_file["TCON"] = TCON(encoding=3, text=[tags["genre"]])

            track_str = tags.get("track_num", "")
            if tags.get("track_total"):
                track_str += f"/{tags['track_total']}"
            if track_str:
                audio_file["TRCK"] = TRCK(encoding=3, text=[track_str])

            disc_str = tags.get("disc_num", "")
            if tags.get("disc_total"):
                disc_str += f"/{tags['disc_total']}"
            if disc_str:
                audio_file["TPOS"] = TPOS(encoding=3, text=[disc_str])

            if tags.get("comment"):
                audio_file["COMM::eng"] = COMM(
                    encoding=3, lang="eng", desc="", text=[tags["comment"]]
                )

        elif isinstance(audio_file, FLAC):
            if tags.get("artist"):
                audio_file["ARTIST"] = [tags["artist"]]
            if tags.get("album"):
                audio_file["ALBUM"] = [tags["album"]]
            if tags.get("title"):
                audio_file["TITLE"] = [tags["title"]]
            if tags.get("year"):
                audio_file["DATE"] = [tags["year"]]
            if tags.get("genre"):
                audio_file["GENRE"] = [tags["genre"]]
            if tags.get("track_num"):
                audio_file["TRACKNUMBER"] = [tags["track_num"]]
            if tags.get("track_total"):
                audio_file["TRACKTOTAL"] = [tags["track_total"]]
            if tags.get("disc_num"):
                audio_file["DISCNUMBER"] = [tags["disc_num"]]
            if tags.get("disc_total"):
                audio_file["DISCTOTAL"] = [tags["disc_total"]]
            if tags.get("comment"):
                audio_file["COMMENT"] = [tags["comment"]]

        audio_file.save()
        return True

    except Exception as e:
        print(f"Error applying tags to {file_path}: {e}")
        return False


def get_file_hash(file_path: str) -> str | None:
    if not os.path.exists(file_path):
        return None

    hash_sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_sha256.update(chunk)
    return hash_sha256.hexdigest()


def extract_basic_info(file_path: str) -> BasicInfo | None:
    try:
        audio_file = MutagenFile(file_path)
        filename = os.path.splitext(os.path.basename(file_path))[0]

        artist = ""
        title = ""
        album = ""

        if audio_file:
            if isinstance(audio_file, MP3):
                tpe1 = audio_file.get("TPE1")
                artist = str(tpe1[0]) if tpe1 else ""
                tit2 = audio_file.get("TIT2")
                title = str(tit2[0]) if tit2 else ""
                talb = audio_file.get("TALB")
                album = str(talb[0]) if talb else ""
            elif isinstance(audio_file, FLAC):
                artist_tag = audio_file.get("ARTIST")
                artist = str(artist_tag[0]) if artist_tag else ""
                title_tag = audio_file.get("TITLE")
                title = str(title_tag[0]) if title_tag else ""
                album_tag = audio_file.get("ALBUM")
                album = str(album_tag[0]) if album_tag else ""

        if not artist and not title:
            if " - " in filename:
                parts = filename.split(" - ", 1)
                if len(parts) == 2:
                    if parts[0].isdigit() or (
                        len(parts[0]) <= 3 and parts[0].replace(".", "").isdigit()
                    ):
                        title = parts[1]
                    else:
                        artist = parts[0]
                        title = parts[1]
            else:
                title = filename

        if not album:
            parent_dir = os.path.basename(os.path.dirname(file_path))
            if parent_dir and parent_dir != os.path.basename(
                os.path.dirname(os.path.dirname(file_path))
            ):
                album = parent_dir

        return {
            "file_path": file_path,
            "artist": artist.strip(),
            "title": title.strip(),
            "album": album.strip(),
            "filename": filename,
        }
    except Exception as e:
        print(f"Error extracting info from {file_path}: {e}")
        return None


def search_musicbrainz(
    artist: str, title: str, album: str = ""
) -> MusicBrainzResult | None:
    try:
        query_parts: list[str] = []
        if artist:
            query_parts.append(f'artist:"{artist}"')
        if title:
            query_parts.append(f'recording:"{title}"')
        if album:
            query_parts.append(f'release:"{album}"')

        if not query_parts:
            return None

        query = " AND ".join(query_parts)
        url = f"https://musicbrainz.org/ws/2/recording/?query={quote(query)}&fmt=json&limit=5"

        print(f"  Searching: {artist} - {title}")

        headers = {"User-Agent": "musictk/0.1.0 (https://github.com/404Simon/musictk)"}
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code != 200:
            print(f"  API error: {response.status_code}")
            return None

        data: dict[str, Any] = response.json()
        recordings: list[dict[str, Any]] = data.get("recordings", [])

        if not recordings and album:
            print("  Retrying without album filter...")
            query_parts_no_album: list[str] = []
            if artist:
                query_parts_no_album.append(f'artist:"{artist}"')
            if title:
                query_parts_no_album.append(f'recording:"{title}"')

            query = " AND ".join(query_parts_no_album)
            url = f"https://musicbrainz.org/ws/2/recording/?query={quote(query)}&fmt=json&limit=5"

            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                recordings = data.get("recordings", [])

        if not recordings:
            return None

        recording = recordings[0]

        result: MusicBrainzResult = {
            "title": recording.get("title", ""),
            "artist": "",
            "album": "",
            "year": "",
            "track_num": "",
            "track_total": "",
            "genre": "",
            "mbid": recording.get("id", ""),
        }

        if "artist-credit" in recording:
            artists: list[str] = []
            for credit in recording["artist-credit"]:
                if "artist" in credit:
                    artists.append(credit["artist"]["name"])
            result["artist"] = ", ".join(artists)

        if "releases" in recording:
            releases: list[dict[str, Any]] = recording["releases"]
            if releases:
                preferred_release = releases[0]
                for rel in releases:
                    rel_group = rel.get("release-group", {})
                    secondary_types = rel_group.get("secondary-types", [])
                    if "Compilation" not in secondary_types:
                        preferred_release = rel
                        break

                release = preferred_release
                result["album"] = release.get("title", "")

                if "date" in release:
                    date = release["date"]
                    if date and len(date) >= 4:
                        result["year"] = date[:4]

                if "media" in release:
                    for medium in release["media"]:
                        if "tracks" in medium:
                            for track in medium["tracks"]:
                                if (
                                    track.get("recording", {}).get("id")
                                    == recording["id"]
                                ):
                                    result["track_num"] = track.get("number", "")
                                    result["track_total"] = str(
                                        medium.get("track-count", "")
                                    )
                                    break

        return result

    except Exception as e:
        print(f"  Error searching: {e}")
        return None


def get_cover_art_url(mbid: str, album_name: str = "") -> str | None:
    try:
        if mbid:
            url = f"https://musicbrainz.org/ws/2/recording/{mbid}?inc=releases&fmt=json"
            headers = {
                "User-Agent": "musictk/0.1.0 (https://github.com/404Simon/musictk)"
            }
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                data: dict[str, Any] = response.json()
                releases: list[dict[str, Any]] = data.get("releases", [])

                for release in releases:
                    release_id = release.get("id")
                    if release_id:
                        cover_url = (
                            f"https://coverartarchive.org/release/{release_id}/front"
                        )
                        cover_response = requests.head(cover_url, timeout=5)
                        if cover_response.status_code == 200:
                            return str(cover_url)

        if album_name:
            itunes_url = f"https://itunes.apple.com/search?term={quote(album_name)}&media=music&entity=album&limit=1"
            response = requests.get(itunes_url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                results: list[dict[str, Any]] = data.get("results", [])
                if results:
                    artwork_url = results[0].get("artworkUrl100")
                    if artwork_url:
                        return str(artwork_url).replace("100x100bb", "500x500bb")

        return None

    except Exception as e:
        print(f"  Error getting cover art: {e}")
        return None


def download_cover_art(url: str) -> bytes | None:
    try:
        print("  Downloading cover art...")
        response = requests.get(url, timeout=30)

        if response.status_code != 200:
            return None

        return bytes(response.content)

    except Exception as e:
        print(f"  Error downloading cover art: {e}")
        return None


def embed_cover_art(file_path: str, cover_data: bytes) -> bool:
    try:
        audio_file = MutagenFile(file_path)

        if audio_file is None:
            return False

        if isinstance(audio_file, MP3):
            if audio_file.tags is not None:
                audio_file.tags.add(
                    APIC(
                        encoding=3,
                        mime="image/jpeg",
                        type=3,
                        desc="Cover",
                        data=cover_data,
                    )
                )
            audio_file.save()
            return True
        elif isinstance(audio_file, FLAC):
            picture = Picture()
            picture.data = cover_data
            picture.type = 3
            picture.mime = "image/jpeg"
            picture.desc = "Cover"

            audio_file.clear_pictures()
            audio_file.add_picture(picture)
            audio_file.save()
            return True

        return False

    except Exception as e:
        print(f"  Error embedding cover art: {e}")
        return False


def apply_auto_tags(file_path: str, tag_data: MusicBrainzResult) -> bool:
    try:
        audio_file = MutagenFile(file_path)

        if audio_file is None:
            return False

        if isinstance(audio_file, MP3):
            if tag_data.get("title"):
                audio_file["TIT2"] = TIT2(encoding=3, text=[tag_data["title"]])
            if tag_data.get("artist"):
                audio_file["TPE1"] = TPE1(encoding=3, text=[tag_data["artist"]])
            if tag_data.get("album"):
                audio_file["TALB"] = TALB(encoding=3, text=[tag_data["album"]])
            if tag_data.get("year"):
                audio_file["TDRC"] = TDRC(encoding=3, text=[tag_data["year"]])
            if tag_data.get("genre"):
                audio_file["TCON"] = TCON(encoding=3, text=[tag_data["genre"]])

            track_str = tag_data.get("track_num", "")
            if tag_data.get("track_total"):
                track_str += f"/{tag_data['track_total']}"
            if track_str:
                audio_file["TRCK"] = TRCK(encoding=3, text=[track_str])

        elif isinstance(audio_file, FLAC):
            if tag_data.get("title"):
                audio_file["TITLE"] = [tag_data["title"]]
            if tag_data.get("artist"):
                audio_file["ARTIST"] = [tag_data["artist"]]
            if tag_data.get("album"):
                audio_file["ALBUM"] = [tag_data["album"]]
            if tag_data.get("year"):
                audio_file["DATE"] = [tag_data["year"]]
            if tag_data.get("genre"):
                audio_file["GENRE"] = [tag_data["genre"]]
            if tag_data.get("track_num"):
                audio_file["TRACKNUMBER"] = [tag_data["track_num"]]
            if tag_data.get("track_total"):
                audio_file["TRACKTOTAL"] = [tag_data["track_total"]]

        audio_file.save()
        return True

    except Exception as e:
        print(f"Error applying tags to {file_path}: {e}")
        return False


def manual_edit_mode(path: str, json_path: str) -> None:
    print("=== Manual Edit Mode ===")
    print("Scanning for MP3/FLAC files...")
    audio_files = get_audio_files(path)

    if not audio_files:
        print("No MP3/FLAC files found!")
        raise click.Abort

    print(f"Found {len(audio_files)} files")
    print("Extracting current tags...")

    tags_list: list[AudioTags] = []
    for file_path in audio_files:
        print(f"  {os.path.basename(file_path)}")
        tags = extract_tags(file_path)
        if tags:
            tags_list.append(tags)

    write_json(tags_list, json_path)
    print(f"\nTags exported to: {json_path}")

    original_hash = get_file_hash(json_path)

    print("Opening in nvim...")
    try:
        subprocess.run(["nvim", json_path], check=False)
    except KeyboardInterrupt:
        print("\nEditor interrupted")
        return
    except Exception as e:
        print(f"Error opening nvim: {e}")
        raise click.Abort from e

    if not os.path.exists(json_path):
        print("JSON file was deleted, no changes to apply.")
        return

    current_hash = get_file_hash(json_path)

    if current_hash != original_hash:
        print("\nJSON file was modified, applying changes...")

        try:
            modified_tags = read_json(json_path)
        except Exception as e:
            print(f"Error reading JSON: {e}")
            return

        success_count = 0
        for tags in modified_tags:
            if apply_tags(tags):
                success_count += 1
            else:
                print(f"Failed to apply tags to: {tags.get('file_path', 'unknown')}")

        print(f"\n✓ Successfully updated {success_count}/{len(modified_tags)} files")
    else:
        print("\nNo changes detected in JSON file.")


def auto_tag_mode(path: str, no_cover: bool, delay: float) -> None:
    print("=== Auto Tag Mode ===")
    print("Scanning for MP3/FLAC files...")
    audio_files = get_audio_files(path)

    if not audio_files:
        print("No MP3/FLAC files found!")
        raise click.Abort

    print(f"Found {len(audio_files)} files")

    success_count = 0
    cover_downloads = 0
    downloaded_albums: set[str] = set()

    for i, file_path in enumerate(audio_files):
        print(f"\n[{i+1}/{len(audio_files)}] {os.path.basename(file_path)}")

        basic_info = extract_basic_info(file_path)
        if not basic_info:
            print("  - Could not extract basic info")
            continue

        tag_data = search_musicbrainz(
            basic_info["artist"], basic_info["title"], basic_info["album"]
        )

        if tag_data:
            artist = tag_data["artist"]
            title = tag_data["title"]
            album = tag_data["album"]
            print(f"  ✓ Found: {artist} - {title} ({album})")

            if apply_auto_tags(file_path, tag_data):
                success_count += 1
                print("  ✓ Tags applied")

                if not no_cover:
                    album_key = f"{artist}|{album}".lower()

                    if album_key in downloaded_albums:
                        print("  - Cover art already downloaded for this album")
                    else:
                        cover_url = get_cover_art_url(
                            tag_data.get("mbid", ""), tag_data["album"]
                        )
                        if cover_url:
                            cover_data = download_cover_art(cover_url)
                            if cover_data:
                                downloaded_albums.add(album_key)
                                if embed_cover_art(file_path, cover_data):
                                    cover_downloads += 1
                                    print("  ✓ Cover art embedded")
                                else:
                                    print("  ! Failed to embed cover art")
                            else:
                                print("  ! Failed to download cover art")
                        else:
                            print("  - No cover art found")
            else:
                print("  ! Failed to apply tags")
        else:
            print("  - No match found")

        if i < len(audio_files) - 1:
            time.sleep(delay)

    print("\n=== Results ===")
    print(f"Successfully tagged: {success_count}/{len(audio_files)} files")
    if not no_cover:
        print(f"Cover art downloaded: {cover_downloads} files")
