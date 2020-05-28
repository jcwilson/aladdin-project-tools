#!/usr/bin/env python3
"""
Commands for working with the project's components.

Once you ``poetry install`` this project, you can invoke these commands at the command line.


.. code-block:: shell
    :caption: When not in a poetry shell

    $ poetry run components --help


.. code-block:: shell
    :caption: When in an activated poetry shell

    $ components --help
"""

import enum
import hashlib
import importlib.resources
import json
import logging
import os
import pathlib
import subprocess
import textwrap
from typing import Iterable, List, Tuple

import typer
import jsonschema
import yaml
from networkx import DiGraph
from networkx.algorithms import dag
from networkx.algorithms.cycles import find_cycle
from networkx.exception import NetworkXNoCycle


from . import LogLevel, install_coloredlogs

# Created in the callback
logger = None

app = typer.Typer(add_completion=False)
"""
:autoapiskip:
"""

# Discover the project's component directories
_components_path = pathlib.Path("components")
Component = enum.Enum(
    "Component",
    {item: item for item in os.listdir(_components_path) if os.path.isdir(_components_path / item)},
    type=str,
)
"""
The project components.
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
    Commands for working with the project's components.
    \f

    :param ctx: The typer invocation context.
    :param log_level: The Python logger log level for this command.
    """
    global logger

    install_coloredlogs(log_level=log_level.value)

    logger = logging.getLogger(ctx.invoked_subcommand)


@app.command()
def validate(components: List[Component] = typer.Argument(None)):
    """
    Validate the components' component.yaml files.

    :param components: The components to validate, default is all of them.
    """
    _validate_components(components or Component)


@app.command("list")
def _list():
    """List all of the current components."""
    logger.info("Current components: %s", ", ".join(component.value for component in Component))


@app.command()
def create(name: pathlib.Path = typer.Argument(None)):
    """
    Add a new component to the project.
    \f

    :param name: The name of the new component.
    """
    if not name:
        name = pathlib.Path(typer.prompt("What is the name of the new component?"))

    if len(name.parts) != 1:
        logger.error("Component name must be a valid file name and not be a path")
        raise typer.Abort()

    component = name
    path = pathlib.Path("components") / component

    # Create the component directory
    try:
        logger.info("Creating component directory")
        path.mkdir()
    except Exception:
        logger.error("Could not create component directory")
        raise typer.Abort()

    # Build the component image
    logger.info("Building component image")
    if _aladdin_build(components=[component]):
        logger.error("Could not build component")
        raise typer.Abort()

    # Prompt them to create their pyproject.toml and add some python library dependencies
    if typer.confirm("Configure python dependencies with poetry?", default=True):
        if not _docker_run(
            component=component,
            tag="local",
            command=["poetry", "init"],
            workdir=pathlib.Path("/code") / component,
        ):
            logger.info("Created %s/pyproject.toml", path.as_posix())

            # Build the component image again with the new dependencies
            logger.info("Building component image")
            if _aladdin_build(components=[component]):
                logger.error("Could not build component")
                raise typer.Abort()
        else:
            logger.error("Could not initialize the poetry project for the component")
            raise typer.Abort()
    else:
        logger.notice(
            "Use the 'components edit %s' command to create/update this component's"
            " pyproject.toml file",
            component,
        )

    # # Prompt them to potentially create a Dockerfile for their component
    # if typer.confirm("Create a Dockerfile for the new component?", default=True):
    #     with open(path / "Dockerfile", "w") as dockerfile:
    #         dockerfile.write(
    #             textwrap.dedent(
    #                 """
    #                 ### BASIC DOCKERFILE ###########################################################
    #                 # Edit this file to further specialize your component image
    #                 ################################################################################
    #                 ARG FROM_IMAGE
    #                 FROM $FROM_IMAGE
    #                 """
    #             ).strip()
    #         )
    #     logger.info("%s/Dockerfile created", path.as_posix())

    logger.success("New component '%s' created", component)
    logger.info(
        "Run this component with 'components edit %s' to update your poetry dependencies", component
    )


@app.command()
def build(components: List[Component] = typer.Argument(None)):
    """
    Build the docker images for the project's components.

    This will also perform validation on the components before attempting the build, too.
    \f

    .. note::
        This command is essentially ``aladdin build``, but is present here if one is more
        comfortable using ``component`` commands to interact with this project.

    :param components: The list of components to build. If none provided, all components will be
                       built.

    **Examples:**

    .. code-block:: shell
        :caption: Build all components

        $ components build --log-level DEBUG

    .. code-block:: shell
        :caption: Build only the shared and api components

        $ components build --log-level DEBUG shared api
    """
    _validate_components(components or Component)

    raise typer.Exit(_aladdin_build(component.value for component in components))


def _validate_components(components: List[Component]):
    """
    Validate the components' component.yaml files.

    :param component: The component to validate.
    """
    try:
        with importlib.resources.path("aladdin_project_tools", "etc") as etc:
            schema_file_path = etc / "component_schema.json"

        with open(schema_file_path) as schema_file:
            schema = json.load(schema_file)
    except Exception as e:
        logger.error("Failed to load schema file %s: %s", schema_file_path.as_posix(), e)
        raise typer.Abort()
    else:
        jsonschema.Draft7Validator.check_schema(schema)

    for component in components:
        component_yaml = _get_component_config(component)
        if not component_yaml:
            continue

        try:
            jsonschema.validate(instance=component_yaml, schema=schema)
        except jsonschema.exceptions.ValidationError as e:
            logger.error("Invalid component.yaml for %s component:\n%s", component.value, e)
            raise typer.Abort()


def _get_component_graph() -> DiGraph:
    """
    Get the dependency graph for our components.

    This reads the ``component.yaml`` file for each component to determine dependencies.

    :returns: The dependency graph.
    """
    # Create the graph
    components = DiGraph()
    components.add_nodes_from(Component)
    for component in Component:
        component_yaml = _get_component_config(component)
        components.add_edges_from(
            (Component[dependency], component)
            for dependency in component_yaml.get("dependencies", [])
        )

    # Confirm that no cycles are present
    try:
        cycles = find_cycle(components)
    except NetworkXNoCycle:
        return components
    else:
        raise RuntimeError("Cycles found in component dependency graph", cycles)


def _get_component_config(component: Component) -> dict:
    """
    Read the contents of the component's component.yaml yaml file.

    :param component: The component whose component.yaml you wish to retrieve.
    :returns: The config contents or the empty dictionary if it was not present.
    """
    try:
        with open(
            pathlib.Path("components") / component.value / "component.yaml"
        ) as component_yaml_file:
            return yaml.safe_load(component_yaml_file)
    except FileNotFoundError:
        return {}


def _get_dependents_for(component: Component) -> Tuple[str]:
    """
    Get a list of all other components that depend on ``component`` at some level.

    :param component: The dependency component.
    :return: The list of dependent components in topological order.
    """
    components = get_component_graph()
    dependents = dag.descendants(components, component)
    return tuple(dag.topological_sort(components.subgraph(dependents)))


@app.command()
def run(
    component: Component,
    mount: pathlib.Path = typer.Option(
        "/code",
        help=textwrap.dedent(
            """
            The container directory at which to mount the components directory.

            Default: /code
            """
        ),
    ),
    command: List[str] = typer.Argument(None),
):
    """
    Run a command in a component's container.

    This will mount the components/ directory in the container.

    This doesn't precisely run the actual component's image, as oftentimes one will wish to
    have an ENTRYPOINT and CMD already baked into the image. This runs an image with the sole
    difference being that the ENTRYPOINT and CMD settings have been cleared. This gives us the
    flexbility to get in and explore the container without compromising the image intended to be
    published.
    \f

    :param component: The component container to run.
    :param mount: The container path at which to mount the ``commponents/`` directory, defaults to
                  the container's working directory, defaults to ``/code``.
    :param command: Any remaining arguments will be passed to the container as its ``run`` command,
                    defaults to ``/bin/bash``.

                    .. important:: If these arguments contain ``-`` or ``--`` flags, you will need
                                   to preface this argument list with ``--``.

    **Examples:**

    .. code-block:: shell
        :caption: Run the default CMD for the ``pipeline-flake8`` container

        $ components run pipeline-flake8

    .. code-block:: shell
        :caption: Run a specific CMD for the ``pipeline`` container

        $ components run pipeline prospector

    .. code-block:: shell
        :caption: Run a specific CMD with complex arguments for the ``pipeline`` container

        $ components run pipeline -- black --check --diff --target-version py38 .
    """
    raise typer.Exit(
        _docker_run(
            component=component.value,
            tag="editor",
            mount=mount,
            command=list(command or ("/bin/bash",)),
        )
    )


@app.command()
def edit(
    component: Component,
    mount: pathlib.Path = typer.Option(
        "/code",
        help=textwrap.dedent(
            """
            The container directory at which to mount the components directory.

            Default: /code
            """
        ),
    ),
):
    """
    Run the editor container for the specified component.

    This facilitates editing the poetry dependencies in the container that requires them. It assumes
    the image uses poetry to manage its python dependencies.

    This will mount the components/ directory in the container, but place you in the component's
    specific directory to start.

    If the poetry.lock file is changed, this will then rebuild this component and any components
    that depend upon it.
    \f

    :param component: The component whose dependencies you wish to edit.

    **Example:**

    .. code-block:: shell
        :caption: Start a bash shell in the /code/api directory of the api container

        $ components edit api
    """
    poetry_lock_md5 = _get_poetry_lock_file_md5_digest(component)

    if _docker_run(
        component=component.value,
        tag="editor",
        mount=mount,
        command=["/bin/bash"],
        workdir=pathlib.Path("/code") / component.value,
    ):
        logger.warning("Encountered an error when editing the component")
        raise typer.Abort()

    if poetry_lock_md5 == _get_poetry_lock_file_md5_digest(component):
        logger.info("No changes detected; Will not rebuild the component image")
        raise typer.Exit()

    dependents = _get_dependents_for(component)
    logger.notice(
        "Changes detected; Building the updated component image and its dependent components: %s",
        ", ".join(dependent.value for dependent in dependents),
    )
    if _aladdin_build([component.value]):
        logger.error("Failed to build %s component after you edited it", component.value)
        raise typer.Exit(1)

    if _aladdin_build([dependent.value for dependent in dependents]):
        logger.error(
            "Failed to build all dependent components after you edited %s", component.value
        )
        raise typer.Exit(1)


def _get_poetry_lock_file_md5_digest(component: Component) -> str:
    """
    Get the md5 digest of the contents of the poetry lock file.

    :param component: The component whose poetry.lock file you wish to hash.
    :return: The md5 digest, or None if the file was not present.
    """
    poetry_lock_path = pathlib.Path("components") / component.value / "poetry.lock"
    if poetry_lock_path.exists():
        with open(poetry_lock_path, "rb") as poetry_lock_file:
            md5 = hashlib.md5(poetry_lock_file.read())
        return md5.hexdigest()


def _aladdin_build(components: Iterable[str] = ()) -> int:
    """
    Build the provided components (or all of them, if none provided here).

    :param components: The components to build.
    :return: The return code of the aladdin build command.
    """
    command = ["aladdin", "build"]
    command.extend(components)

    return subprocess.call(command)


def _docker_run(
    component,
    tag: str = "local",
    mount: pathlib.Path = pathlib.Path("/code"),
    command: List[str] = None,
    workdir: pathlib.Path = None,
) -> int:
    """
    Run a component's image with the build context mounted as a host volume.

    :param component: The component whose image to run.
    :param tag: The docker :-suffix tag of the image to run, defaults to ``'local'``.
    :param mount: The container directory to mount the build context at, defaults to ``'/code'``.
    :param command: The command to run in the container.
    :param workdir: An alternative directory to start the command in.
    :return: The error code of the docker run command. 0 indicates success.
    """
    command = command or []

    cwd = os.getcwd()
    normalized_cwd = cwd[len("/cygdrive") :] if cwd.startswith("/cygdrive") else cwd

    with open("lamp.json") as lamp_file:
        lamp_data = json.load(lamp_file)

    project_name = lamp_data["name"]
    image_name = f"{project_name}-{component}:{tag}"

    command = (
        ["docker", "run", "--rm", "-it", "-v", f"{normalized_cwd}/components:{mount}"]
        + (["-w", workdir.as_posix()] if workdir else [])
        + [image_name]
        + command
    )

    logger.debug("Running docker container: %s", " ".join(command))

    return subprocess.call(command)
