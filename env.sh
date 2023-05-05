#! /bin/sh
# copy environment from working directory next to miniagi.py
cp /app/.env .
python miniagi.py "${*}"
