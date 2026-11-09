"""Compatibility entry point for the household command line."""
from flask.cli import FlaskGroup

from . import create_app

main = FlaskGroup(create_app=create_app)

if __name__ == "__main__":
    main()
