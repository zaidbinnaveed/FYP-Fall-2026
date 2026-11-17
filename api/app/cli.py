"""Administrative CLI: ``python -m app.cli <command>``.

D0 provides ``version`` and ``ensure-bucket``. ``create-admin``, ``seed-helplines``,
``import-hospitals`` and ``seed-kb`` arrive with the phases that own them (D1, D3, D5).
"""

from __future__ import annotations

import typer

from app import __version__
from app.adapters.storage import StorageAdapter, StorageError
from app.core.config import get_settings
from app.core.logging import configure_logging

cli = typer.Typer(no_args_is_help=True, add_completion=False)


@cli.command()
def version() -> None:
    """Print the API version."""
    typer.echo(__version__)


@cli.command("ensure-bucket")
def ensure_bucket() -> None:
    """Create the private storage bucket if it does not exist (idempotent)."""
    settings = get_settings()
    configure_logging(settings.log_level, service="cli")
    try:
        created = StorageAdapter(settings).ensure_bucket()
    except StorageError as exc:
        typer.echo(f"storage error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"bucket {settings.storage_bucket}: {'created' if created else 'exists'}")


if __name__ == "__main__":
    cli()
