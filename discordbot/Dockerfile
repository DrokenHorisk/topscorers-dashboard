FROM python:3.11-slim


RUN apt-get update && apt-get install -y --no-install-recommends \
ca-certificates libjpeg62-turbo libfreetype6 libpng16-16 fonts-dejavu-core \
&& rm -rf /var/lib/apt/lists/*


WORKDIR /app


COPY discordbot/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt


COPY discordbot/bot.py /app/bot.py
COPY discordbot/topscorers.py /app/topscorers.py
COPY backend/app /app/backend_app
ENV PYTHONPATH="/app/backend_app:${PYTHONPATH}"


RUN mkdir -p /data
ENV MPLBACKEND=Agg


CMD ["python", "-u", "bot.py"]