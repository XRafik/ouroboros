# Deliberately separate build and clean desktop roots. Neither is a release image.
ARG UBUNTU_IMAGE=ubuntu:22.04@sha256:0a9887931b0e38af2e3487ed39e29436b0535c4f3f52e57745baaf79d1898956
FROM ${UBUNTU_IMAGE} AS common
ARG DEBIAN_FRONTEND=noninteractive
RUN printf '%s\n' \
    'deb [check-valid-until=no] https://snapshot.ubuntu.com/ubuntu/20261020T000000Z jammy main universe' \
    'deb [check-valid-until=no] https://snapshot.ubuntu.com/ubuntu/20261020T000000Z jammy-updates main universe' \
    'deb [check-valid-until=no] https://snapshot.ubuntu.com/ubuntu/20261020T000000Z jammy-security main universe' \
    > /etc/apt/sources.list
# The base image lacks CA roots: use the signed Ubuntu archive to bootstrap them,
# then use HTTPS for all remaining package downloads.
RUN sed -i 's|https://snapshot|http://snapshot|g' /etc/apt/sources.list \
    && apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && sed -i 's|http://snapshot|https://snapshot|g' /etc/apt/sources.list \
    && apt-get update && apt-get install -y --no-install-recommends python3 git curl
FROM common AS builder
RUN sed -n 's/^deb /deb-src /p' /etc/apt/sources.list > /etc/apt/sources.list.d/native-sources.list \
    && apt-get update
RUN apt-get install -y --no-install-recommends build-essential pkg-config \
    libgirepository1.0-dev libcairo2-dev libwebkit2gtk-4.1-dev \
    libgtk-3-bin librsvg2-common glib-networking gsettings-desktop-schemas \
    gstreamer1.0-plugins-base gstreamer1.0-plugins-good bubblewrap xdg-dbus-proxy \
    adwaita-icon-theme hicolor-icon-theme shared-mime-info
RUN curl -fLsS https://github.com/astral-sh/uv/releases/download/0.12.1/uv-x86_64-unknown-linux-gnu.tar.gz -o /tmp/uv.tar.gz \
    && echo '90b2f223fb69d19db49e117da601f64978593417988530aa733d456141b4bcbb  /tmp/uv.tar.gz' | sha256sum -c - \
    && tar -xzf /tmp/uv.tar.gz -C /opt && ln -s /opt/uv-x86_64-unknown-linux-gnu/uv /usr/local/bin/uv
FROM common AS desktop
RUN apt-get install -y --no-install-recommends xvfb openbox xdotool x11-utils x11-apps \
    dbus-x11 fonts-dejavu-core libgl1-mesa-dri libgl1 libegl1 libgbm1 libdrm2 imagemagick \
    && for package in libwebkit2gtk-4.1-0 libgtk-3-0 gir1.2-webkit2-4.1 python3-gi; do \
         if dpkg-query -W "$package" 2>/dev/null; then exit 1; fi; \
       done
# WebKit's sandbox is left enabled; never test it as root or grant privileged.
RUN useradd -m -u 1000 qualifier
USER qualifier
