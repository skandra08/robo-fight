# Build from this folder: docker build -t my-bot .
# Match sandbox: no network, read-only root (writable /tmp), 1 CPU, 512 MB, map at /arena.
FROM python:3.13-slim
WORKDIR /bot
COPY mechfight.py bot.py world.py cover.py nav.py combat.py memory.py levers.py pathing.py ./
COPY data ./data
ENTRYPOINT ["python3", "-u", "/bot/bot.py"]
