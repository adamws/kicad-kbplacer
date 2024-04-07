#!/bin/sh

if [ -z "$CIRCLE_SHA1" ]; then
  KBPLACER_REVISION=master
else
  KBPLACER_REVISION=$CIRCLE_SHA1
fi
docker build --build-arg="KBPLACER_REVISION=$KBPLACER_REVISION" -t absolem .
docker cp $(docker create --name absolem absolem:latest /bin/sh):/absolem.zip .
docker rm absolem
