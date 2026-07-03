#!/bin/sh
# Container entrypoint: run the app as the unprivileged `prelegal` user.
#
# The container starts as root only long enough to make /data writable —
# host bind mounts (and volumes created by the pre-hardening image, which
# ran everything as root) arrive owned by root or by an arbitrary host
# uid, and SQLite needs write access to the directory. After the chown we
# drop privileges permanently with setpriv (in util-linux, present in
# python:*-slim).
#
# If the container is started with an explicit --user, we're not root,
# can't chown, and shouldn't try — just run as whoever we are.
set -eu

if [ "$(id -u)" = "0" ]; then
    chown -R prelegal:prelegal /data
    exec setpriv --reuid prelegal --regid prelegal --init-groups "$@"
fi

exec "$@"
