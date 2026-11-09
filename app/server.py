"""Loopback-only managed server behind Tailscale Serve or another local proxy."""

import os

from waitress import serve

from . import create_app


def main():
    serve(
        create_app(),
        host="127.0.0.1",
        port=int(os.environ.get("MEAL_ROULETTE_PORT", "5057")),
        threads=4,
        trusted_proxy="127.0.0.1",
        trusted_proxy_count=1,
        trusted_proxy_headers={"x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-port"},
        clear_untrusted_proxy_headers=True,
    )


if __name__ == "__main__":
    main()
