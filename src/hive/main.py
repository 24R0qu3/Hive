import argparse
import logging

from hive.log import setup

logger = logging.getLogger(__name__)

LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]

def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", default="WARNING", choices=LEVELS,
                        help="Console log level")
    parser.add_argument("--log-file", default="DEBUG", choices=LEVELS,
                        help="File log level")
    parser.add_argument("--log-path", default="hive.log",
                        help="Path to log file")
    args = parser.parse_args()

    setup(
        console_level=args.log,
        file_level=args.log_file,
        log_path=args.log_path,
    )

    logger.info("Hive started")
