import argparse
import logging

from hive.log import setup

logger = logging.getLogger(__name__)

LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--log", default="WARNING", choices=LEVELS, help="Console log level"
    )
    parser.add_argument(
        "--log-file", default="DEBUG", choices=LEVELS, help="File log level"
    )
    parser.add_argument("--log-path", default=None, help="Path to log file")
    args = parser.parse_args()

    kwargs = {"console_level": args.log, "file_level": args.log_file}
    if args.log_path:
        kwargs["log_path"] = args.log_path

    setup(**kwargs)

    logger.info("Hive started")

    from hive.ui.app import HiveApp
    HiveApp().run()


if __name__ == "__main__":
    run()
