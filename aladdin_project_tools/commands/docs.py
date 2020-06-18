#!/usr/bin/env python3
"""
Commands for working with the project's documentation.

Once you ``poetry install`` this project, you can invoke these commands at the command line.

.. code-block:: shell
    :caption: When not in a poetry shell

    $ poetry run docs --help


.. code-block:: shell
    :caption: When in an activated poetry shell

    $ docs --help
"""

import importlib.resources
import json
import logging
import pathlib
import shutil
import subprocess
from typing import List

import jsonschema
import typer
import yaml
from sphinx.cmd.build import main as sphinx_main

from . import LogLevel, install_coloredlogs

# Created in the callback
logger = None

app = typer.Typer(add_completion=False)
"""
:autoapiskip:
"""


@app.callback()
def main(
    ctx: typer.Context,
    log_level: LogLevel = typer.Option(
        LogLevel.INFO, help="Set the Python logger log level for this command."
    ),
):
    """
    Commands for generating the documentation.
    \f

    :param ctx: The typer-provided context for the command invocation.
    :param log_level: The Python logger log level for this command.
    """
    global logger

    install_coloredlogs(log_level=log_level.value)

    logger = logging.getLogger(ctx.invoked_subcommand)


@app.command()
def build(
    show: bool = typer.Option(False, help="Open the docs in a browser after they have been built."),
    sphinx_args: List[str] = typer.Argument(None),
):
    """
    Build the documentation.
    \f

    :param show: Open the docs in a browser after they have been built, defaults to False.
    :param sphinx_args: Any remaining arguments will be passed to the underlying ``sphinx_main()``
                        function that actually builds the docs.

                        .. important::
                            If these arguments contain ``-`` or ``--`` flags, you will need to
                            preface this argument list with ``--``.

    **Examples:**

    .. code-block:: shell
        :caption: Simple build

        $ docs build

    .. code-block:: shell
        :caption: Open the docs afterwards

        $ docs build --show

    .. code-block:: shell
        :caption: Perform a full rebuild with debug logging

        $ docs --log-level DEBUG build -- a
    """
    # Check that both the schema and the sample component.yaml file are correct
    _validate_component_schema()

    built_path = pathlib.Path("docs") / "built"
    logger.info("Generating docs at %s", built_path.as_posix())

    result = sphinx_main(["-b", "html", "docs/source", "docs/built"])
    if not result:
        logger.success("Docs generated at %s", built_path.as_posix())
    else:
        logger.error("Docs not generated")
        raise typer.Abort("Failed to build docs")

    if show:
        logger.notice("Opening generated docs in a browser")
        typer.launch((built_path / "index.html").as_posix())


def _validate_component_schema():
    """
    Check that both the schema and the sample_component.yaml file are correct.

    The schema at least is also validated at component build time. We just want to do our best to
    ensure that the documentation doesn't stray from the functionality.
    """
    try:
        with importlib.resources.path("aladdin_project_tools", "etc") as etc:
            schema_file_path = etc / "component_schema.json"
            sample_standard_file_path = etc / "sample_standard_component.yaml"
            sample_compatible_file_path = etc / "sample_compatible_component.yaml"

        with open(schema_file_path) as schema_file:
            schema = json.load(schema_file)
    except Exception as e:
        logger.error("Failed to load schema file %s: %s", schema_file_path.as_posix(), e)
        raise typer.Abort()
    else:
        try:
            jsonschema.Draft7Validator.check_schema(schema)
        except jsonschema.exceptions.SchemaError as e:
            logger.error("Invalid etc/component_schema.json\n%s", e)
            raise typer.Abort()

    for sample_file_path in [sample_standard_file_path, sample_compatible_file_path]:
        with open(sample_file_path) as component_file:
            component_yaml = yaml.safe_load(component_file)

        try:
            jsonschema.validate(instance=component_yaml, schema=schema)
        except jsonschema.exceptions.ValidationError as e:
            logger.error(f"Invalid etc/{sample_file_path.name}\n%s", e)
            raise typer.Abort()


@app.command()
def show():
    """
    Open the documentation in a browser.
    \f

    **Example:**

    .. code-block:: shell
        :caption: Open the docs

        $ docs show
    """
    logger.notice("Opening generated docs in a browser")
    built_path = pathlib.Path("docs") / "built" / "index.html"
    typer.launch(built_path.as_posix())
