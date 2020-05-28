###########
Development
###########

************
Using poetry
************
This project uses poetry_ as its package manager and build system. It offers support for deterministic installation of dependencies by utilizing a lock file as well as other useful features to assist application and library development.

While most development operations take place inside of docker containers or in a kubernetes cluster, there are still some things that need to run directly from the development machine. We use `poetry scripts`_ to manage those operations. All of the project-level operations take place in a python virtual environment that poetry automatically creates and maintains for us. See the :ref:`development:Project scripts` section below for more information.

.. _poetry: https://python-poetry.org/
.. _poetry scripts: https://python-poetry.org/docs/pyproject/#scripts


Getting started
===============
The first thing you'll want to do is create a virtual environment and install this project (and implicitly all of its dependencies).

.. code-block:: shell

    $ poetry install

Then activate the virtual environment with

.. code-block:: shell

    $ poetry shell

Now you have access to all of the project's dependencies, including dev dependencies, so you can do things like run `pytest` and such without affecting your system's python installation. You will probably want to always be in the poetry shell when working on this project, so be sure to run this command any time you open a new terminal to begin work here.


Project scripts
===============
One poetry feature that we make use of is its ability to create first-order CLI commands from python scripts. When we ran the ``poetry install`` command, it installed a few executables in the virtual environment's ``bin`` directory. You can see their configuration in the ``pyproject.toml`` file:

.. code-block:: toml

    [tool.poetry.scripts]
    docs = "bin.commands.docs:app"
    components = "bin.commands.components:app"

While in the poetry shell, you can run these as CLI commands:

.. code-block::

    $ components --help
    Usage: components [OPTIONS] COMMAND [ARGS]...

      Commands for working with the project's components.

    Options:
      --log-level [NOTSET|SPAM|DEBUG|VERBOSE|INFO|NOTICE|WARN|WARNING|SUCCESS|ERROR|CRITICAL|FATAL]
                                      Set the Python logger log level for this
                                      command.

      --install-completion [bash|zsh|fish|powershell|pwsh]
                                      Install completion for the specified shell.
      --show-completion [bash|zsh|fish|powershell|pwsh]
                                      Show completion for the specified shell, to
                                      copy it or customize the installation.

      --help                          Show this message and exit.

    Commands:
      build     Build the docker images for the project's components.
      create    Add a new component to the project.
      edit      Run the editor container for the specified component.
      list      List all of the current components.
      run       Run a command in a component's container.
      validate  Validate the components' component.yaml files.


*********************
Developing components
*********************
A component is simply a collection of assets (code, binaries, images, etc) that you wish to publish as a docker image. These images can be used for any purpose including:

- a pod container image to be used a kubernetes deployment
- local instantiation for CI purposes
- a building block to be included in another component's image

All defined component operations are available through the ``components`` CLI command. To get more details on a particular sub-command's usage, use the ``--help`` flag.

.. code-block:: shell

    $ components --help
    $ components build --help


Structure of a component
========================
All components live in the ``components/`` directory. All files are optional. See below for how each one can be used to modify the component's resulting docker image.

.. code-block:: text

    <project root>/
        build/
            ...
        components/
            <name of your component>/
                .dockerignore
                component.yaml
                pyproject.toml
                poetry.lock
                Dockerfile
                # All other content like code, entrypoint
                # scripts and component-specific configuration
                # also go in here.
                # These will all be made available in the
                # docker build context so you can COPY them
                # into your image if need be.
        docs/
            ...
        helm/
            ...
        ...

If you provide none of the files listed above, your component image will still be built and contain the contents of your component directory. It will just have the "aladdinized" version of the base image for your language. (Currently only python3 is supported). This means the following changes will be made to the base image:

- The python system libraries will be pre-compiled with the appropriate optimizaton level for the build context (unoptimized for dev, ``-O`` otherwise)
- The working directory will be set to ``/code`` and ``/code`` will be added to the ``PYTHONPATH``
- The ``aladdin-user`` will be created in the ``aladdin-user`` group, along with its home directory
- The ``poetry`` tool will be installed and available to ``aladdin-user``


The ``.dockerignore`` file
--------------------------
Each component can define its own ``.dockerignore`` file that will be appended to the global ``components/.dockerignore``. Any entries in here should be relative to the component's directory, as the build system will provide the build context-relative prefix automatically.


The ``Dockerfile``
------------------
You may also provide your own ``Dockerfile``. This will allow you do perform your own specialization not covered by installing python packages through poetry. You can alter the user and their home directory and the build system will detect this and adapt when installing ``poetry`` and python package dependencies.

The docker build context is always the ``components/`` directory. The build system uses dynamic ``.dockerignore`` files to limit the scope of what's available in the build context, though. For instance, performing a ``COPY . .`` command in your component's ``Dockerfile`` will only copy over your component's directory. (This is just an example, as this exact ``COPY`` command is already part of the image building process. In practice, you will rarely need to do your own ``COPY``-ing.)

.. warning::
    If you set the ``WORKDIR`` in your ``Dockerfile``, all of your component's assets and your component's dependencies' assets will also be placed in the new ``WORKDIR``, too. You probably don't want to set your own ``WORKDER`` unless you have some special use case. It is recommended that you leave it as ``/code``, and if you wish to use a different working directory when running the container, use the ``docker run -w <workdir>`` option or the ``workingDir:`` setting in your helm templates.


The ``pyproject.toml`` and ``poetry.lock`` files
------------------------------------------------
You will probably provide your own ``pyproject.toml`` and ``poetry.lock`` files to specify which python packages your component needs. See the :ref:`development:Edit a component's python dependencies` section below for details about this.


The ``component.yaml`` file
---------------------------
The component build system makes some assumptions about your component:

- It is written in Python 3
- The base image of ``python:3.8-slim`` is acceptable
- You wish to have poetry installed in the container
- You wish for the container process to run as ``aladdin-user``
- It has no dependencies on other components in this project
- The working directory will be ``/code`` and it will be added to the ``PYTHONPATH``

If any of these assumptions do not hold true for your component, you will need to create a ``component.yaml`` file to customize the image build process for your component. Use the file to choose an alternative base image and/or adjust which changes from above are applied.

.. important::
    If you specify a base image in the ``component.yaml`` file, it will not be "aladdinized" or have ``poetry`` installed by default. It is assumed you are using a different base image for reasons other than building a standard "code" component. You can still instruct the system to apply those changes, but the default behavior is to not apply them when you use a different base image.

.. Pull this file in from outside of the docs/ directory
.. literalinclude:: ../../aladdin_project_tools/etc/component_schema.json
  :language: JSON
  :caption: The ``component.yaml`` schema

.. Pull this file in from outside of the docs/ directory
.. literalinclude:: ../../aladdin_project_tools/etc/sample_component.yaml
  :language: YAML
  :caption: Example ``component.yaml`` file


The rest
--------
Every other file and directory is up to you!


Create a new component
======================
Run the following command and follow the prompts to create a new component. If you opt out of all of the guided setup steps, you will still have added a component with the simplest possible configuration, an empty directory, under ``components/``. It will be the aladdinized ``python:3.8-slim`` image.

.. code-block:: shell

    $ components create

The prompt will offer you the chance to add python package dependencies by running ``poetry init`` to create a poetry ``pyproject.toml`` file for your component. If you do, it will then update your component image to build these dependencies into the image. Even if you don't know what packages you'll need yet for your component, it is recommended that you still opt to configure your dependencies with poetry to create the basic ``pyproject.toml`` file. You can edit it later with the ``components edit`` command.

The prompt will also offer you the chance to create a new (empty) ``Dockerfile`` for your component. Once you edit it, build your component again to pick up the changes. Chances are you won't need to do this at first unless you know for sure that you'll need to build upon the basic "aladdinized" image. You can always add it later, as well


Build a component
=================
We wrap the ``aladdin build`` command with the ``components build`` command. It performs some extra validation before delegating to ``aladdin build``.

.. code-block:: shell

    $ components build [components]...

If you specify no components, it will build all of the components in the project. Even with a complex project with many components, the build system's use of multi-stage builds and ``Dockerfile`` caching should keep build times to a minimum. Still, specifying the one or two components you need to rebuild can save you some time during day-to-day development.

When a component is built, first all of the other components listed in its ``component.yaml`` dependencies list are built (and their dependencies, too, recursively). For each dependency built in this manner, its python package dependencies and its assets are copied into the component image being built using the docker multi-stage builder pattern. **In this way we can avoid costly rebuilds of shared assets and dependencies by placing reusable code and libraries in a shared component.** The shared component will be built once and then its assets copied to all other components that depend upon it.

Once the component is built, it's ready for use. You should now be able to reference it your helm templates and ``git hooks`` scripts and so on.


Run a component
===============
For quick tests or debugging, you may be able to run your component with a direct ``docker run`` invocation. Presuming your image does not use the "exec form" for its ``ENTRYPOINT`` and you are able to run arbitrary commands against it, you can run your component image. By default, it will mount the ``components`` directory at ``/code`` in the container.

.. code-block:: shell

    $ components run <component> [command]...


Edit a component's python dependencies
======================================
Every time a component image is built, an additional "editor" image is built alongside it. This to allow easier editing of poetry-managed python package dependencies. This is very similar to running the component image, except its default ``ENTRYPOINT`` and ``CMD`` values are cleared and you are dropped right into a ``bash`` shell in your component's directory. In situations where you cannot run the container due to a strict ``ENTRYPOINT`` or missing environment variables, using this ``edit`` sub-command is a useful option to inspect your container's contents.

.. code-block:: shell

    $ components edit <component>

Run this command to be dropped into a container where you can immediately run `poetry add/remove/update` commands. Since the local filesystem's ``components/`` directory will be mounted into the container, any edits to the ``pyproject.toml`` or ``poetry.lock`` files will be preserved. Upon successfully exiting the container, the image will automatically be built again if any changes to the ``poetry.lock`` file were detected.

To simply update all of your package dependencies to the latest versions allowed by your ``pyproject.toml``, use the ``poetry update`` command.

.. code-block:: shell

    # In the poetry shell
    $ components edit <component>

    # In the component's container
    $ poetry update

You can also edit the dependencies by hand, though it's not recommended. If you do, be sure to update the lock file. Remember, the lock file is the source of truth for what gets installed in your component image.:

.. code-block:: shell

    # In the poetry shell
    $ components edit <component>

    # In the component's container
    $ poetry lock

.. note:: These dependencies are specific to the component and are fully contained within the component's docker image and container. They do not interact with the main project's poetry configuration or shell environment at all.


************************
Generating documentation
************************
The documentation operations are available through the ``docs`` CLI command. To get more details on a particular sub-command's usage, use the ``--help`` flag.

.. code-block:: shell

    $ docs --help
    $ docs build --help


Write the docs
==============
We use Sphinx_ and `Restructured Text`_ (reST or rST) for both our descriptive documentation and code documentation.

.. _Sphinx: https://www.sphinx-doc.org/en/master/
.. _Restructured Text: https://docutils.sourceforge.io/docs/ref/rst/restructuredtext.html


Code documentation
------------------
We use the Sphinx autoapi_ extension to discover and generate documentation from our code comments. It is smart enough to describe the prescriptive aspects of our code where we use Python type annotations, but developers are still responsible for providing context and explanation to best communicate the code's behavior and intent.

.. _autoapi: https://sphinx-autoapi.readthedocs.io/en/latest/index.html


Project documentation
---------------------
You can find the source files in the ``docs/source`` directory.


Build the docs
==============
Build the HTML documentation with the following command:

.. code-block:: shell

    $ docs build [--show]

Specify ``--show`` to open them in your browser after they are built.

To show the docs without building them again, run:

.. code-block:: shell

    $ docs show
