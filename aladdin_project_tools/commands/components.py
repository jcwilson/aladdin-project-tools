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
import shutil
import subprocess
import textwrap
import time
from typing import Iterable, List, Tuple, Union

import click
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


class ComponentType(str, enum.Enum):
    Standard = "1"
    Compatible = "2"
    Traditional = "3"


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
def create(
    name: pathlib.Path = typer.Argument(None),
    component_type: ComponentType = typer.Option(
        ComponentType.Standard,
        hidden=True,
        prompt=textwrap.dedent(
            """
            What kind of component do you wish to create?

            1) Standard - An aladdin component where most of the boilerplate is taken
                          care of for you already. It will be built from the default
                          python base image.
            2) Compatible - Use this if you need to use an alternative base image, but
                            it's still a python-based image. You will still be able to
                            compose other components into this component's image.
            3) Traditional - No special handling will take place and you must provide your
                             own Dockerfile.
            """
        ),
        show_choices=False,
    ),
):
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

    component = name.as_posix()
    path = pathlib.Path("components") / component

    if path.exists():
        typer.confirm("Directory already exists. Delete and recreate?", abort=True)
        logger.notice("Deleting existing directory")
        shutil.rmtree(path)

    # Create the component directory
    try:
        logger.notice("Creating component directory")
        path.mkdir()
    except Exception:
        logger.error("Could not create component directory")
        raise typer.Abort()

    with open("lamp.json") as lamp_file:
        lamp = json.load(lamp_file)

    # Delete the editor image, if it exists
    project_name = lamp["name"]
    editor_image = f"{project_name}-{component}:editor"
    subprocess.run(["docker", "rmi", "-f", editor_image], capture_output=True)

    if component_type == ComponentType.Standard:
        _create_standard_component(lamp, component)
    elif component_type == ComponentType.Compatible:
        _create_compatible_component(lamp, component)
    else:
        _create_traditional_component(lamp, component)


def _create_standard_component(lamp: dict, component: str) -> None:
    """
    Create a component where you only need to provide your component's code and asset content.

    One may further specialize their component image by providing a Dockerfile in their component
    directory.

    :param lamp: The lamp file data.
    :param component: The name of the component to create.
    """
    path = pathlib.Path("components") / component

    # component_yaml_data["language"]["name"] = typer.prompt("Image language:", default="python")
    # We only support Python at the moment
    language_name = "python"
    language_version = typer.prompt("Image language version:", default="3.8")

    available = set(c.name for c in Component if c.name != component)
    dependencies = []
    if available and typer.confirm("Does this component depend upon any others?", default=True):
        try:
            while True:
                dep = typer.prompt(
                    "Enter a component",
                    prompt_suffix="\nCtrl-C to finish: ",
                    type=click.Choice(available),
                    show_choices=True,
                )
                available.remove(dep)
                dependencies.append(dep)
        except typer.Abort:
            print()

    # Create the initial component.yaml file
    with open(path / "component.yaml", "w") as component_yaml:
        component_yaml.write(
            yaml.dump(
                {
                    "meta": {"version": 1},
                    "language": {"name": language_name, "version": language_version},
                    "dependencies": dependencies,
                }
            )
        )

    logger.notice("Created %s/component.yaml file", path.as_posix())

    # Prompt them to potentially create a Dockerfile for their component
    if typer.confirm("Create a Dockerfile for the new component?", default=False):
        with open(path / "Dockerfile", "w") as dockerfile:
            dockerfile.write(
                textwrap.dedent(
                    """
                    ### BASIC DOCKERFILE ###########################################################
                    # Edit this file to further specialize your component image
                    ################################################################################

                    # Warning: If you change the image USER, be sure to update the component.yaml
                    #          file accordingly to ensure that your python packages still work as
                    #          expected.

                    # Warning: Similarly, if you update the base image in the component.yaml file,
                    #          ensure that the component.yaml python language version is updated to
                    #          match the base image's python version (if it changed).

                    # Note: Do not provide any FROM instructions in this file.
                    """
                ).strip()
            )

        logger.notice("Created %s/Dockerfile", path.as_posix())

    # Build the component image so we can use poetry to add dependencies
    logger.info("Building initial component image")
    if _aladdin_build(components=[component]).returncode:
        logger.error("Could not build component")
        raise typer.Abort()

    # Prompt them to create their pyproject.toml and add some python library dependencies
    if _docker_run(
        component=component,
        tag="local",
        command=["poetry", "init", "--name", f"{lamp['name']}-{component}"],
        in_component_dir=True,
    ).returncode:
        logger.error("Could not initialize the poetry project for the component")
        raise typer.Abort()

    logger.notice("Created %s/pyproject.toml", path.as_posix())

    # Build the component image again with the new dependencies
    logger.info("Building component image")
    if _aladdin_build(components=[component]).returncode:
        logger.error("Could not build component")
        raise typer.Abort()

    logger.success("New component '%s' created", component)
    logger.notice(
        "Run this component with 'components edit %s' to update your poetry dependencies", component
    )


def _create_compatible_component(lamp: dict, component: str) -> None:
    """
    This creates a component image for a component based on an image other than the default.

    By default, it will skip some of the setup that is done for the standard component image, like
    creating a user account. It also requires more information to be provided in the component.yaml
    so that any component dependencies can be installed correctly.

    :param lamp: The lamp file data.
    :param component: The name of the component to create.
    """
    path = pathlib.Path("components") / component

    component_yaml_data = {
        "meta": {"version": 1},
        "language": {"name": "python"},
        "image": {"base": None, "user": {"name": None, "group": None, "home": None}},
        "dependencies": [],
    }

    # component_yaml_data["image"]["base"] = typer.prompt("What base image will you use?")
    component_yaml_data["image"]["base"] = "jupyter/minimal-notebook:latest"

    python_version, user_info = _get_image_info(component_yaml_data["image"]["base"])

    component_yaml_data["language"]["version"] = typer.prompt(
        "Image python version:", default=python_version
    )
    component_yaml_data["image"]["user"]["name"] = typer.prompt(
        "Image user name:", default=user_info["name"]
    )
    component_yaml_data["image"]["user"]["group"] = typer.prompt(
        "Image user group:", default=user_info["group"]
    )
    component_yaml_data["image"]["user"]["home"] = typer.prompt(
        "Image user home:", default=user_info["home"]
    )

    available = set(c.name for c in Component if c.name != component)
    if available and typer.confirm("Does this component depend upon any others?", default=True):
        try:
            while True:
                dep = typer.prompt(
                    "Enter a component",
                    prompt_suffix="\nCtrl-C to finish: ",
                    type=click.Choice(available),
                    show_choices=True,
                )
                available.remove(dep)
                component_yaml_data["dependencies"].append(dep)
        except typer.Abort:
            print()

    # Create the initial component.yaml file
    with open(path / "component.yaml", "w") as component_yaml:
        component_yaml.write(yaml.dump(component_yaml_data))

    logger.notice("Created %s/component.yaml file", path.as_posix())

    # Prompt them to potentially create a Dockerfile for their component
    if typer.confirm("Create a Dockerfile for the new component?", default=False):
        with open(path / "Dockerfile", "w") as dockerfile:
            dockerfile.write(
                textwrap.dedent(
                    """
                    ### BASIC DOCKERFILE ###########################################################
                    # Edit this file to further specialize your component image
                    ################################################################################

                    # Note: Do not provide any FROM instructions in this file.
                    """
                ).strip()
            )

        logger.notice("Created %s/Dockerfile", path.as_posix())

    # Build the component image so we can use poetry to add dependencies
    logger.info("Building initial component image")
    if _aladdin_build(components=[component]).returncode:
        logger.error("Could not build component")
        raise typer.Abort()

    # Prompt them to create their pyproject.toml and add some python library dependencies
    if _docker_run(
        component=component,
        tag="local",
        command=["poetry", "init", "--name", f"{lamp['name']}-{component}"],
        in_component_dir=True,
    ).returncode:
        logger.error("Could not initialize the poetry project for the component")
        raise typer.Abort()

    logger.notice("Created %s/pyproject.toml", path.as_posix())

    # Build the component image again with the new dependencies
    logger.info("Building component image")
    if _aladdin_build(components=[component]).returncode:
        logger.error("Could not build component")
        raise typer.Abort()

    logger.success("New component '%s' created", component)
    logger.notice(
        "Run this component with 'components edit %s' to update your poetry dependencies", component
    )


def _get_image_info(image: str) -> Tuple[str, dict]:
    """
    Retrieve the python version and user details of the image.

    :param image: The image to inspect.
    :returns: The python version and user details.
    """
    try:
        # Perform a "no context" docker build
        tag = f"{image}-extractor"
        _docker_build(
            tags=tag,
            dockerfile=textwrap.dedent(
                f"""
                FROM {image}
                CMD "/bin/sh"
                ENTRYPOINT []
                """
            ).encode(),
        )

        return (_get_python_version(tag), _get_user_info(tag))

    finally:
        subprocess.run(["docker", "rmi", tag])


def _get_python_version(image_name) -> str:
    """
    Determine the version of the image's python installation.

    :param image_name: The image to inspect.
    :returns: The python version.
    """
    ps = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            image_name,
            "python",
            "-c",
            "import platform; print(platform.python_version())",
        ],
        capture_output=True,
        check=True,
    )
    return ps.stdout.decode().strip()


def _get_user_info(image_name) -> dict:
    """
    Retrieve the user name, group and home directory from a docker image.

    :param image_name: The image to inspect.
    """
    ps = subprocess.run(
        ["docker", "run", "--rm", image_name, "bash", "-c", "whoami && groups && echo $HOME"],
        capture_output=True,
        check=True,
    )
    return dict(zip(("name", "group", "home"), ps.stdout.decode().strip().split()))


def _get_workdir(image_name) -> str:
    """
    Retrieve the WORKDIR from a docker image.

    :param image_name: The image to inspect.
    """
    ps = subprocess.run(
        ["docker", "run", "--rm", image_name, "pwd"], capture_output=True, check=True
    )
    return ps.stdout.decode().strip()


def _create_traditional_component(lamp: dict, component: str) -> None:
    """
    Build an image without leveraging any of the build system features.

    This is essentially the "opt-out" option. The build system will perform a vanilla "docker build"
    with the "components/" directory as the build context.

    :param lamp: The lamp file data.
    :param component: The name of the component to create.
    """
    path = pathlib.Path("components") / component
    base_image = typer.prompt("What base image will you use?")

    # Prompt them to potentially create a Dockerfile for their component
    if typer.confirm("Create a Dockerfile for the new component?", default=True):
        with open(path / "Dockerfile", "w") as dockerfile:
            dockerfile.write(
                textwrap.dedent(
                    f"""
                    ### TRADITIONAL DOCKERFILE #####################################################
                    # Edit this file to further specialize your component image
                    ################################################################################

                    FROM {base_image}
                    """
                ).strip()
            )

        logger.notice("Created %s/Dockerfile", path.as_posix())

        # Build the component image so we can use poetry to add dependencies
        logger.info("Building initial component image")
        if _aladdin_build(components=[component]).returncode:
            logger.error("Could not build component")
            raise typer.Abort()


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

    raise typer.Exit(_aladdin_build(component.value for component in components).returncode)


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
        _validate_component(component, schema)


def _validate_component(component: Component, schema: dict) -> None:
    component_yaml = _get_component_config(component)
    dockerfile_path = pathlib.Path("components") / component.value / "Dockerfile"

    if component_yaml:
        try:
            jsonschema.validate(instance=component_yaml, schema=schema)
        except jsonschema.exceptions.ValidationError as e:
            logger.error("Invalid component.yaml for %s component:\n%s", component.value, e)
            raise typer.Abort()

        # TODO: Ensure that there is no FROM instruction in the Dockerfile

    elif dockerfile_path.exists():
        pass
    else:
        logger.error(
            "Component '%s' must provide either component.yaml or Dockerfile", component.value
        )
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


def _get_component_config(component: Union[str, Component]) -> dict:
    """
    Read the contents of the component's component.yaml yaml file.

    :param component: The component whose component.yaml you wish to retrieve.
    :returns: The config contents or the empty dictionary if it was not present.
    """
    component_name = component.value if isinstance(component, Component) else component
    try:
        with open(
            pathlib.Path("components") / component_name / "component.yaml"
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
    components = _get_component_graph()
    dependents = dag.descendants(components, component)
    return tuple(dag.topological_sort(components.subgraph(dependents)))


@app.command()
def run(component: Component, command: List[str] = typer.Argument(None)):
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
            component=component.value, tag="editor", command=list(command or ("/bin/bash",))
        ).returncode
    )


@app.command()
def edit(component: Component):
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
    with open("lamp.json") as lamp_file:
        lamp = json.load(lamp_file)

    project_name = lamp["name"]
    editor_image = f"{project_name}-{component.value}:editor"
    try:
        subprocess.run(["docker", "inspect", editor_image], capture_output=True, check=True)
    except subprocess.CalledProcessError:
        logger.error("No editor image present for this component")
        raise typer.Abort()

    poetry_lock_md5 = _get_poetry_lock_file_md5_digest(component)
    if _docker_run(
        component=component.value, tag="editor", command=["/bin/bash"], in_component_dir=True
    ).returncode:
        logger.warning("Encountered an error when editing the component")
        raise typer.Abort()

    if poetry_lock_md5 == _get_poetry_lock_file_md5_digest(component):
        logger.info("No changes detected; Will not rebuild the component image")
        raise typer.Exit()

    dependents = _get_dependents_for(component)
    if dependents:
        logger.notice(
            "Changes detected; Building the updated component image and any dependent components: %s",
            ", ".join(dependent.value for dependent in dependents),
        )
    else:
        logger.notice("Changes detected; Building the updated component image")

    # Build the component again
    if _aladdin_build([component.value]).returncode:
        logger.error("Failed to build %s component after you edited it", component.value)
        raise typer.Abort()

    # Also rebuild any components that depended on it
    if dependents:
        if _aladdin_build([dependent.value for dependent in dependents]).returncode:
            logger.error(
                "Failed to build all dependent components after you edited %s", component.value
            )
            raise typer.Abort()


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


def _aladdin_build(components: Iterable[str] = ()) -> subprocess.CompletedProcess:
    """
    Build the provided components (or all of them, if none provided here).

    :param components: The components to build.
    :return: The completed process object
    """
    command = ["aladdin", "build"]
    command.extend(components)
    return subprocess.run(command)


def _docker_run(
    component: str, tag: str = "local", command: List[str] = None, in_component_dir: bool = False
) -> subprocess.CompletedProcess:
    """
    Run a component's image with the build context mounted as a host volume.

    :param component: The component whose image to run.
    :param tag: The docker :-suffix tag of the image to run, defaults to ``'local'``.
    :param in_component_dir: Run the command in the component directory rather than the
                             container working directory.
    :param command: The command to run in the container.
    :return: The completed process object
    """
    command = command or []

    with open("lamp.json") as lamp_file:
        lamp_data = json.load(lamp_file)

    project_name = lamp_data["name"]
    image = f"{project_name}-{component}:{tag}"

    workdir = pathlib.Path(_get_workdir(image))
    component_dir = (workdir / component) if in_component_dir else None

    cwd = os.getcwd()
    cwd = cwd[len("/cygdrive") :] if cwd.startswith("/cygdrive") else cwd

    command = (
        ["docker", "run", "--rm", "-it", "-v", f"{cwd}/components:{workdir}"]
        + (["-w", component_dir.as_posix()] if component_dir else [])
        + [image]
        + command
    )

    logger.debug("Running docker container: %s", " ".join(command))

    return subprocess.run(command)


def _docker_build(
    tags: Union[str, List[str]],
    buildargs: dict = None,
    dockerfile: Union[pathlib.Path, bytes] = None,
) -> None:
    """
    A convenience wrapper for calling out to "docker build".

    We always send the same context: the entire components/ directory.

    :param tags: The tags to be applied to the built image.
    :param buildargs: Values for ARG instructions in the dockerfile.
    :param dockerfile: The dockerfile to build against. If not provided, it's assumed that a
                       Dockerfile is present in the context directory. If it's a bytes object, it
                       will be provided to the docker build process on stdin and a "no context"
                       build will take place. Otherwise, a normal docker build will be performed
                       with the specified Dockerfile.
    """
    buildargs = buildargs or {}
    buildargs.setdefault("CACHE_BUST", str(time.time()))

    cmd = ["env", "DOCKER_BUILDKIT=1", "docker", "build"]

    for key, value in buildargs.items():
        cmd.extend(["--build-arg", f"{key}={value}"])

    tags = [tags] if isinstance(tags, str) else tags
    for tag in tags:
        cmd.extend(["--tag", tag])

    if isinstance(dockerfile, bytes):
        # If we receive the Dockerfile as content, we should pipe it to stdin.
        # This is the "no context" build.
        cmd.extend(["-"])
    else:
        # Otherwise, they can specify the path to the Dockerfile to use or let docker
        # find one in the context directory.
        if dockerfile:
            cmd.extend(["-f", dockerfile.as_posix()])
        cmd.extend(["components"])

    logger.debug("Docker build command: %s", " ".join(cmd))
    _check_call(cmd, stdin=dockerfile if isinstance(dockerfile, bytes) else None)


def _check_call(cmd: List[str], stdin: bytes = None) -> None:
    """
    Make a subprocess call and indent its output to match our python logging format.

    :param cmd: The command to run.
    :param stdin: Data to send to the subprocess as its input.
    """
    if stdin is None:
        subprocess.run(cmd, check=True)
    else:
        ps = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        stdout, stderr = ps.communicate(input=stdin)
        if ps.returncode:
            raise subprocess.CalledProcessError(ps.returncode, cmd)
