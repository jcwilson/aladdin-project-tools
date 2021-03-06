### CREATE A BUILDER IMAGE #############################################################
# This image will hold all of the tools required for building python packages. It will
# be used to build python packages before copying them out using the multi-stage
# builder pattern.
########################################################################################
FROM python:3.8-slim

# Install packages required to build native library components
RUN apt-get update \
 && apt-get -y --no-install-recommends install \
    gettext \
    gcc \
    g++ \
    make \
    libc6-dev
# We intenionally do not clear the lists here, as one may wish to derive their own
# builder image from this one, and it doesn't make sense to force them to do their
# own apt-get update. The image size here isn't as much of a concern, since none of
# these build tools will end-up in the final built image.

# Upgrade pip
RUN pip install --no-cache --upgrade pip

RUN apt-get -y --no-install-recommends install \
    libgraphviz-dev

RUN pip install --no-cache --user \
    networkx \
    pygraphviz

# Move to build directory before copying items to non-fixed location
WORKDIR /build
