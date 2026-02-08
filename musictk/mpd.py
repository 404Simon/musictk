"""MPD integration utilities for musictk."""

from __future__ import annotations

import shutil
import subprocess

import click


def update_mpd_database() -> None:
    """Update MPD database using rmpc if available.

    Checks if rmpc is installed and runs 'rmpc update' to refresh
    the MPD database. Shows user feedback during the process.

    If rmpc is not installed, silently does nothing.
    If rmpc fails, shows a warning but doesn't raise an exception.
    """
    if not shutil.which("rmpc"):
        return

    try:
        click.echo("Updating MPD database...")
        subprocess.run(["rmpc", "update"], check=True, capture_output=True)
        click.echo("MPD database updated successfully")
    except subprocess.CalledProcessError as e:
        click.echo(f"Warning: Failed to update MPD database: {e}", err=True)
    except Exception as e:
        click.echo(f"Warning: Error running rmpc: {e}", err=True)
