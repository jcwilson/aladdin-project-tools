"""Shell scripts available after installing the project."""
import enum
import logging
import os
import pathlib
import typer

import coloredlogs
import verboselogs
import yaml
from networkx import DiGraph
from networkx.algorithms.cycles import find_cycle
from networkx.exception import NetworkXNoCycle

# Discover the logging levels installed by verboselogs
LogLevel = enum.Enum(
    "LogLevel",
    {
        name: name
        for name in sorted(logging._nameToLevel, key=lambda name: logging._nameToLevel[name])
    },
    type=str,
)
"""
The available logging levels.
:autoapiskip:
"""


def install_coloredlogs(log_level: str):
    """
    Setup our enhanced logging functionality.

    :param log_level: The log level to use for the duration of the command.
    """
    verboselogs.install()
    coloredlogs.install(
        level=log_level,
        fmt="%(levelname)-8s %(message)s",
        level_styles=dict(
            spam=dict(color="green", faint=True),
            debug=dict(color="black", bold=True),
            verbose=dict(color="blue"),
            info=dict(color="white"),
            notice=dict(color="magenta"),
            warning=dict(color="yellow"),
            success=dict(color="green", bold=True),
            error=dict(color="red"),
            critical=dict(color="red", bold=True),
        ),
        field_styles=dict(
            asctime=dict(color="green"),
            hostname=dict(color="magenta"),
            levelname=dict(color="white"),
            name=dict(color="white", bold=True),
            programname=dict(color="cyan"),
            username=dict(color="yellow"),
        ),
    )
