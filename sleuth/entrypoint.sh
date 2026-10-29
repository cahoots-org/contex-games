#!/bin/sh
# Railway mounts volumes as root: hand /data to the game's user, then run as that user.
set -e
if [ -d /data ]; then
    chown -R sleuth:sleuth /data
fi
exec setpriv --reuid=sleuth --regid=sleuth --init-groups "$@"
