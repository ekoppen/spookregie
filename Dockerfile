# Multi-stage build voor de beheerpagina (backend + gebouwde frontend in één image).
# Mirror-node en scare-node draaien op hun eigen Pi's met camera/GPIO/audio-
# toegang en horen hier bewust niet bij — dit image is alleen de centrale
# beheerpagina.

FROM node:20-alpine AS frontend-build

WORKDIR /build

COPY admin/frontend/package.json admin/frontend/package-lock.json ./
RUN npm ci
COPY admin/frontend/ ./
RUN npm run build


FROM python:3.12-slim AS backend

WORKDIR /app

COPY admin/requirements.txt ./admin/requirements.txt
RUN pip install --no-cache-dir -r admin/requirements.txt

COPY shared/ ./shared/
COPY admin/app/ ./admin/app/
COPY admin/run.py ./admin/run.py
COPY --from=frontend-build /build/dist ./admin/frontend/dist

# Niet als root draaien; /data is waar de database/media/logs terechtkomen
# (zie ADMIN_DB_PATH/ADMIN_MEDIA_DIR/LOG_DIR in docker-compose.yml).
RUN useradd --create-home --shell /usr/sbin/nologin beheerder \
    && mkdir -p /data \
    && chown -R beheerder:beheerder /app /data
USER beheerder

EXPOSE 8000

CMD ["python3", "-m", "admin.run"]
