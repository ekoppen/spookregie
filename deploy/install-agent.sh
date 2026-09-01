#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/ekoppen/spookregie.git"
REPO_DIR="$HOME/spookregie"
ENV_FILE="$HOME/.spookregie/env"

echo "== Spookregie device-installatie =="

command -v git >/dev/null 2>&1 || { echo "git niet gevonden -- installeer git eerst."; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 niet gevonden -- installeer python3 eerst."; exit 1; }

if [ ! -d "$REPO_DIR/.git" ]; then
  git clone "$REPO_URL" "$REPO_DIR"
else
  echo "Repo bestaat al op $REPO_DIR, sla clone over."
fi

python3 -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install -q -r "$REPO_DIR/mirror_node/requirements.txt"

mkdir -p "$(dirname "$ENV_FILE")"
if [ ! -f "$ENV_FILE" ]; then
  read -rp "MQTT-host: " mqtt_host
  read -rp "MQTT-poort [1883]: " mqtt_port
  mqtt_port="${mqtt_port:-1883}"
  read -rp "MQTT-gebruiker (leeg = geen auth): " mqtt_user
  read -rsp "MQTT-wachtwoord: " mqtt_pass
  echo
  read -rp "MQTT-topic-prefix (leeg = geen): " mqtt_topic_prefix
  read -rp "Beheerpagina-URL [http://localhost:8000]: " backend_url
  backend_url="${backend_url:-http://localhost:8000}"

  cat > "$ENV_FILE" <<EOF
MQTT_HOST=$mqtt_host
MQTT_PORT=$mqtt_port
MQTT_USER=$mqtt_user
MQTT_PASS=$mqtt_pass
MQTT_TOPIC_PREFIX=$mqtt_topic_prefix
BACKEND_URL=$backend_url
SPOOKREGIE_REPO_DIR=$REPO_DIR
EOF
  echo "Configuratie opgeslagen in $ENV_FILE"
else
  echo "Configuratiebestand bestaat al op $ENV_FILE, sla vragen over."
fi

PLATFORM="$(uname)"

if [ "$PLATFORM" = "Darwin" ]; then
  echo "-- macOS: LaunchAgents installeren --"
  AGENTS_DIR="$HOME/Library/LaunchAgents"
  mkdir -p "$AGENTS_DIR"

  # ponytail: launchd's plist <key>EnvironmentVariables</key> can only set
  # literal key/value pairs -- it cannot source a file the way systemd's
  # EnvironmentFile= does. So on macOS we need a tiny wrapper that reads
  # ENV_FILE itself and exports each line before exec'ing python; without
  # it, MQTT_HOST/PORT/USER/PASS/TOPIC_PREFIX/BACKEND_URL would silently
  # fall back to mirror_node's hardcoded defaults instead of what was just
  # configured above. Plain `source` would break on a value containing a
  # literal space (bash would try to run the rest as a command), so this
  # loop splits only on '=' and keeps the remainder -- including spaces --
  # intact as the value.
  LAUNCHER="$HOME/.spookregie/run-module.sh"
  cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [ -f "$ENV_FILE" ]; then
  while IFS='=' read -r key value; do
    [ -z "\$key" ] && continue
    export "\$key=\$value"
  done < "$ENV_FILE"
fi
exec "$REPO_DIR/.venv/bin/python" -m "\$1"
EOF
  chmod +x "$LAUNCHER"

  cat > "$AGENTS_DIR/nl.spookregie.mirror.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>nl.spookregie.mirror</string>
  <key>ProgramArguments</key>
  <array>
    <string>$LAUNCHER</string>
    <string>mirror_node.main</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO_DIR</string>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF

  cat > "$AGENTS_DIR/nl.spookregie.agent.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>nl.spookregie.agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>$LAUNCHER</string>
    <string>mirror_node.agent</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>MIRROR_RESTART_COMMAND</key><string>launchctl kickstart -k gui/$(id -u)/nl.spookregie.mirror</string>
  </dict>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF

  launchctl load "$AGENTS_DIR/nl.spookregie.mirror.plist"
  launchctl load "$AGENTS_DIR/nl.spookregie.agent.plist"
  echo "LaunchAgents geladen. Bekijk status met: launchctl list | grep spookregie"

elif [ "$PLATFORM" = "Linux" ]; then
  echo "-- Linux: systemd-services installeren (vereist sudo) --"

  sudo tee /etc/systemd/system/spookregie-mirror.service > /dev/null <<EOF
[Unit]
Description=Spookregie mirror-node
After=network.target

[Service]
Type=simple
WorkingDirectory=$REPO_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$REPO_DIR/.venv/bin/python -m mirror_node.main
Restart=always

[Install]
WantedBy=multi-user.target
EOF

  sudo tee /etc/systemd/system/spookregie-agent.service > /dev/null <<EOF
[Unit]
Description=Spookregie device-agent
After=network.target

[Service]
Type=simple
WorkingDirectory=$REPO_DIR
EnvironmentFile=$ENV_FILE
Environment=MIRROR_RESTART_COMMAND=systemctl restart spookregie-mirror
ExecStart=$REPO_DIR/.venv/bin/python -m mirror_node.agent
Restart=always

[Install]
WantedBy=multi-user.target
EOF

  sudo systemctl daemon-reload
  sudo systemctl enable --now spookregie-mirror spookregie-agent
  echo "systemd-services actief. Bekijk status met: systemctl status spookregie-mirror spookregie-agent"

else
  echo "Onbekend platform: $PLATFORM -- alleen macOS (Darwin) en Linux worden ondersteund."
  exit 1
fi

echo "== Installatie klaar. Ga naar de beheerpagina > Apparaten om dit apparaat aan een output te koppelen. =="
