# Multi-stage build voor de beheerpagina (backend + gebouwde frontend in één image).
# Scare-node draait op zijn eigen Pi met GPIO/audio-toegang en hoort hier
# bewust niet bij. mirror_node's code zit wél in dit image, maar alleen om
# 'm headless (MIRROR_HEADLESS=1) als test-/ontwerp-hulpmiddel te kunnen
# starten vanaf de Spiegel-pagina (zie admin/app/mirror_process.py) -- de
# échte node-deployment (Pi + beamer + systemd) blijft hier volledig los
# van staan.

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
COPY mirror_node/ ./mirror_node/
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
