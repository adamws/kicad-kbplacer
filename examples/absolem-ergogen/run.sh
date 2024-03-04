#!/bin/sh

docker build -t absolem .
docker cp $(docker create --name absolem absolem:latest /bin/sh):/absolem.zip .
docker rm absolem
