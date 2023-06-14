#! /bin/bash

test ${#} -gt 0 || { echo "usage: $0 <prompt>"; exit; }

mkdir -p ./appdata

# copy environment into working directory
cp .env ./appdata

# launch container
docker run -it \
  -v $(pwd)/appdata:/app \
  mini-agi ./env.sh "${*}"

