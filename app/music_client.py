from __future__ import annotations

import subprocess


class MusicAccessError(RuntimeError):
    pass


def play_music() -> str:
    _run_applescript(
        """
        tell application "Music"
            try
                play
            end try
            delay 0.5
            if player state is stopped then
                try
                    play first track of library playlist 1
                on error
                    error "NO_MUSIC_STARTED"
                end try
            end if
        end tell
        """
    )
    return "Ich starte die Wiedergabe in Apple Music."


def pause_music() -> str:
    _run_applescript(
        """
        tell application "Music"
            pause
        end tell
        """
    )
    return "Apple Music ist pausiert."


def next_track() -> str:
    _run_applescript(
        """
        tell application "Music"
            next track
        end tell
        """
    )
    return "Nächster Titel."


def previous_track() -> str:
    _run_applescript(
        """
        tell application "Music"
            previous track
        end tell
        """
    )
    return "Vorheriger Titel."


def play_playlist(name: str) -> str:
    playlist_name = _escape_applescript_text(name)
    script = f"""
    on lowercase(sourceText)
        set upperChars to "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÜ"
        set lowerChars to "abcdefghijklmnopqrstuvwxyzäöü"
        set loweredText to ""
        repeat with charIndex from 1 to length of sourceText
            set currentChar to character charIndex of sourceText
            set foundChar to false
            repeat with mapIndex from 1 to length of upperChars
                if currentChar is character mapIndex of upperChars then
                    set loweredText to loweredText & character mapIndex of lowerChars
                    set foundChar to true
                    exit repeat
                end if
            end repeat
            if foundChar is false then set loweredText to loweredText & currentChar
        end repeat
        return loweredText
    end lowercase

    tell application "Music"
        set targetPlaylist to missing value
        set wantedName to my lowercase("{playlist_name}")
        repeat with playlistRef in every playlist
            if my lowercase(name of playlistRef as string) is wantedName then
                set targetPlaylist to playlistRef
                exit repeat
            end if
        end repeat

        if targetPlaylist is missing value then
            error "PLAYLIST_NOT_FOUND"
        end if

        play targetPlaylist
    end tell
    """
    _run_applescript(script)
    return f"Ich spiele die Playlist {name}."


def list_playlists(limit: int = 12) -> list[str]:
    script = f"""
    set outputText to ""
    set maxPlaylists to {int(limit)}
    set outputCount to 0

    tell application "Music"
        repeat with playlistRef in every playlist
            if outputCount is greater than or equal to maxPlaylists then return outputText
            set playlistName to name of playlistRef as string
            if playlistName is not "" then
                if outputText is "" then
                    set outputText to playlistName
                else
                    set outputText to outputText & linefeed & playlistName
                end if
                set outputCount to outputCount + 1
            end if
        end repeat
    end tell

    return outputText
    """
    output = _run_applescript(script)
    return [line.strip() for line in output.splitlines() if line.strip()]


def play_search(query: str) -> str:
    search_text = _escape_applescript_text(query)
    script = f"""
    tell application "Music"
        set searchResults to search library playlist 1 for "{search_text}" only songs
        if (count of searchResults) is 0 then
            error "SONG_NOT_FOUND"
        end if

        play item 1 of searchResults
    end tell
    """
    _run_applescript(script)
    return f"Ich spiele {query}."


def now_playing() -> dict | None:
    """Current track + playback state for the Dashboard Musik card. Checks via System
    Events first so this never auto-launches Music.app just by being polled - "nothing
    playing" (app not running, or running but stopped) is a normal state, not an error."""
    script = """
    tell application "System Events"
        set musicRunning to (name of processes) contains "Music"
    end tell
    if musicRunning is false then return "NOT_RUNNING"

    tell application "Music"
        if player state is stopped then return "STOPPED"
        set trackName to name of current track
        set trackArtist to artist of current track
        set trackAlbum to album of current track
        set stateText to player state as string
    end tell
    set sep to ASCII character 31
    return trackName & sep & trackArtist & sep & trackAlbum & sep & stateText
    """
    output = _run_applescript(script)
    if output in ("NOT_RUNNING", "STOPPED", ""):
        return None
    parts = output.split("\x1f")
    if len(parts) < 4:
        return None
    title, artist, album, state = parts[0], parts[1], parts[2], parts[3]
    return {
        "title": title,
        "artist": artist or None,
        "album": album or None,
        "is_playing": state == "playing",
    }


def _run_applescript(script: str) -> str:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=12,
        )
    except subprocess.TimeoutExpired:
        raise MusicAccessError(
            "Apple Music hat zu lange nicht geantwortet. Öffne die Musik-App einmal normal "
            "und versuch es dann nochmal."
        )

    if result.returncode == 0:
        return result.stdout.strip()

    error_text = (result.stderr or result.stdout).strip()
    lowered_error = error_text.lower()

    if "not authorized" in lowered_error or "not allowed" in lowered_error:
        raise MusicAccessError(
            "Apple Music Zugriff wurde noch nicht erlaubt. Öffne macOS "
            "Systemeinstellungen > Datenschutz & Sicherheit > Automation "
            "und erlaube Terminal oder VS Code den Zugriff auf Musik."
        )

    if "song_not_found" in lowered_error:
        raise MusicAccessError("Ich habe den Titel in Ihrer Apple-Music-Mediathek nicht gefunden.")

    if "playlist_not_found" in lowered_error:
        raise MusicAccessError("Ich habe diese Playlist in Apple Music nicht gefunden.")

    if "no_music_started" in lowered_error:
        raise MusicAccessError(
            "Apple Music ist geöffnet, aber ich konnte keine Wiedergabe starten. "
            "Starte einmal manuell einen Titel, danach kann ich Wiedergabe und Pause steuern."
        )

    if "application can't be found" in lowered_error:
        raise MusicAccessError("Ich konnte die Musik-App auf diesem Mac nicht finden.")

    raise MusicAccessError(f"Apple Music konnte nicht gesteuert werden: {error_text}")


def _escape_applescript_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", " ")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )
