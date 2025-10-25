FROM python:3.11-slim


RUN apt-get update && apt-get install -y --no-install-recommends \
build-essential curl ca-certificates && \
rm -rf /var/lib/apt/lists/*


WORKDIR /app


COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt


# Script principal (doit exister à la racine du repo)
COPY topscorers_dashboard.py /app/topscorers_dashboard.py


# Backend FastAPI
COPY backend/app /app/app


ENV DASHBOARD_DIR=/data
RUN mkdir -p /data


EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host=0.0.0.0", "--port=8080"]