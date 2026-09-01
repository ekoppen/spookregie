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

PLATFORM="$(uname)"

mkdir -p "$(dirname "$ENV_FILE")"
chmod 700 "$(dirname "$ENV_FILE")"
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

  # mirror_node opent een echt GUI-venster (cv2, geen -headless build) voor
  # de beamer-output -- dat venster heeft een draaiende desktop-/X-sessie
  # nodig om naartoe te tekenen. Op macOS regelt launchd dit vanzelf (native
  # Cocoa-venster, geen DISPLAY nodig); op Linux draait de service als
  # systemd system-unit, die zonder deze twee variabelen geen idee heeft
  # welke X-sessie te gebruiken (Qt-fout "Could not load ... xcb").
  if [ "$PLATFORM" = "Linux" ]; then
    read -rp "DISPLAY van de desktop-sessie met de beamer eraan [:0]: " display
    display="${display:-:0}"
    read -rp "XAUTHORITY-pad van die sessie [\$HOME/.Xauthority]: " xauthority
    xauthority="${xauthority:-$HOME/.Xauthority}"
    cat >> "$ENV_FILE" <<EOF
DISPLAY=$display
XAUTHORITY=$xauthority
EOF
  fi

  chmod 600 "$ENV_FILE"
  echo "Configuratie opgeslagen in $ENV_FILE"
else
  echo "Configuratiebestand bestaat al op $ENV_FILE, sla vragen over."
fi

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

  # opencv-python (mirror_node's cv2, met echt GUI-venster voor de
  # beamer-output -- geen -headless build, zie mirror_node/requirements.txt)
  # linkt bij import al tegen libGL, ook vóórdat er een venster geopend
  # wordt. Op een kale Debian/Raspberry Pi OS-install ontbreekt die vaak,
  # wat de service in een crashloop zet (ImportError: libGL.so.1) --
  # zonder deze regel moest dat handmatig achteraf hersteld worden.
  # `apt-get install` is zelf al idempotent (no-op als 'ie al aanwezig is),
  # dus geen aparte "is 'ie al geinstalleerd"-check nodig.
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq && sudo apt-get install -y libgl1
  fi

  # ponytail: these are system-level units (installed under
  # /etc/systemd/system/ via sudo) which run as root unless told
  # otherwise -- but EnvironmentFile points at $ENV_FILE, which lives in
  # this unprivileged user's home dir and is writable by that user. A
  # root service reading an unprivileged-writable env file is a local
  # privesc primitive (e.g. LD_PRELOAD/PYTHONPATH injection). Run the
  # service processes themselves as the user who ran this install
  # script instead -- sudo is still needed to write the unit files and
  # call systemctl, that part is unchanged.
  INSTALL_USER="$(id -un)"
  INSTALL_GROUP="$(id -gn)"

  sudo tee /etc/systemd/system/spookregie-mirror.service > /dev/null <<EOF
[Unit]
Description=Spookregie mirror-node
After=network.target

[Service]
Type=simple
User=$INSTALL_USER
Group=$INSTALL_GROUP
WorkingDirectory=$REPO_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$REPO_DIR/.venv/bin/python -m mirror_node.main
Restart=always

[Install]
WantedBy=multi-user.target
EOF

  # ponytail: het unprivileged serviceaccount (User=$INSTALL_USER hierboven)
  # kan zelf geen `systemctl restart` op een systemwide unit doen -- dat
  # vereist root/polkit, wat een non-interactive Type=simple service niet
  # kan geven. Deze sudoers-drop-in geeft alleen dat ene vaste commando,
  # zonder argumentvrijheid, dus dit heropent niet de root-privesc die de
  # vorige beveiligingsfix (User=/Group=) juist sloot.
  echo "$INSTALL_USER ALL=(root) NOPASSWD: /bin/systemctl restart spookregie-mirror" \
    | sudo tee /etc/sudoers.d/spookregie >/dev/null
  sudo chmod 440 /etc/sudoers.d/spookregie

  sudo tee /etc/systemd/system/spookregie-agent.service > /dev/null <<EOF
[Unit]
Description=Spookregie device-agent
After=network.target

[Service]
Type=simple
User=$INSTALL_USER
Group=$INSTALL_GROUP
WorkingDirectory=$REPO_DIR
EnvironmentFile=$ENV_FILE
Environment="MIRROR_RESTART_COMMAND=sudo -n /bin/systemctl restart spookregie-mirror"
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
