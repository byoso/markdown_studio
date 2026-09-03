"""
file version: 1.0.0
This modules provides a quick and easy way to use Logger class.
example:

logger = Logger("My Application", level="DEBUG")

logger.debug("that works")

"""


import logging
from typing import Literal

levels = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}
LevelName = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def get_prefix(date: bool = True, name: bool = True, level: bool = True) -> str:
    prefix = ""
    if date:
        prefix += "[%(asctime)s]"
    if name:
        prefix += "[%(name)s]"
    if level:
        prefix += "[%(levelname)s]"
    return prefix + " "

class CustomFormatter(logging.Formatter):

    def __init__(
            self,
            display_date: bool = True,
            display_name: bool = True,
            display_level: bool = True,
            prefix_format: str | None = None,
            ) -> None:
        super().__init__()
        self.display_date = display_date
        self.display_name = display_name
        self.display_level = display_level
        self.prefix_format = prefix_format

    blue = "\033[34m"
    green = "\033[32m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    message = "%(message)s"

    def _build_formats(self) -> dict[int, str]:
        prefix = self.prefix_format
        if prefix is None:
            prefix = get_prefix(self.display_date, self.display_name, self.display_level)

        return {
            logging.DEBUG: self.green + prefix + self.reset + self.message,
            logging.INFO: self.blue + prefix + self.reset + self.message,
            logging.WARNING: self.yellow + prefix + self.reset + self.message,
            logging.ERROR: self.red + prefix + self.reset + self.message,
            logging.CRITICAL: self.bold_red + prefix + self.reset + self.message,
        }


    def format(self, record: logging.LogRecord) -> str:
        formats = self._build_formats()
        log_fmt = formats.get(record.levelno, self.message)
        formatter = logging.Formatter(log_fmt, "%Y-%m-%d %H:%M:%S")
        return formatter.format(record)

class Logger(logging.Logger):
    def __init__(
            self, name: str = __name__,
            level: LevelName = "INFO",
            display_date: bool = True,
            display_name: bool = True,
            display_level: bool = True,
            prefix_format: str | None = None,
            ) -> None:
        super().__init__(name)
        self.console_handler = logging.StreamHandler()
        self.console_handler.setFormatter(
            CustomFormatter(
                display_date=display_date,
                display_name=display_name,
                display_level=display_level,
                prefix_format=prefix_format,
            )
        )
        self.addHandler(self.console_handler)
        self.set_level(level)

    def set_level(self, level: LevelName) -> None:
        super().setLevel(levels[level])
