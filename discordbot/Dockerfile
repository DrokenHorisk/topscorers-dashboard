FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY discordbot/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY discordbot/bot.py /app/bot.py

# /data: pour seen_transfers.json (PVC)
RUN mkdir -p /data
VOLUME ["/data"]

ENV POLL_INTERVAL_SEC=120
CMD ["python", "-u", "bot.py"]
