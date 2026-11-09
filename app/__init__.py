"""The household application factory; importing it never starts a server."""

from .app import create_app

__all__ = ["create_app"]
