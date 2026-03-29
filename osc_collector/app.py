"""Punct de intrare compatibil: pornește interfața principală."""

from __future__ import annotations


def main() -> None:
    from osc_collector.main_ui import run_app

    run_app()


if __name__ == "__main__":
    main()
