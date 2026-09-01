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

  read -rp "Draait hier een mirror/beamer? [J/n]: " wants_mirror
  wants_mirror="${wants_mirror:-j}"
  read -rp "Draait hier een camera? [j/N]: " wants_camera
  wants_camera="${wants_camera:-n}"
  if [[ ! "$wants_mirror" =~ ^[jJ] ]] && [[ ! "$wants_camera" =~ ^[jJ] ]]; then
    echo "Kies minstens één rol (mirror of camera) -- geen van beide is niet geldig." >&2
    exit 1
  fi
  is_mirror=0
  [[ "$wants_mirror" =~ ^[jJ] ]] && is_mirror=1
  is_camera=0
  [[ "$wants_camera" =~ ^[jJ] ]] && is_camera=1

  cat > "$ENV_FILE" <<EOF
MQTT_HOST=$mqtt_host
MQTT_PORT=$mqtt_port
MQTT_USER=$mqtt_user
MQTT_PASS=$mqtt_pass
MQTT_TOPIC_PREFIX=$mqtt_topic_prefix
BACKEND_URL=$backend_url
SPOOKREGIE_REPO_DIR=$REPO_DIR
SPOOKREGIE_IS_MIRROR=$is_mirror
SPOOKREGIE_IS_CAMERA=$is_camera
EOF

  # mirror_node opent een echt GUI-venster (cv2, geen -headless build) voor
  # de beamer-output -- dat venster heeft een draaiende desktop-/X-sessie
  # nodig om naartoe te tekenen. Op macOS regelt launchd dit vanzelf (native
  # Cocoa-venster, geen DISPLAY nodig); op Linux draait de service als
  # systemd system-unit, die zonder deze twee variabelen geen idee heeft
  # welke X-sessie te gebruiken (Qt-fout "Could not load ... xcb"). Alleen
  # relevant voor de mirror-rol -- een camera-only apparaat heeft geen GUI.
  if [ "$is_mirror" = "1" ] && [ "$PLATFORM" = "Linux" ]; then
    read -rp "DISPLAY van de desktop-sessie met de beamer eraan [:0]: " display
    display="${display:-:0}"
    read -rp "XAUTHORITY-pad van die sessie [\$HOME/.Xauthority]: " xauthority
    xauthority="${xauthority:-$HOME/.Xauthority}"
    cat >> "$ENV_FILE" <<EOF
DISPLAY=$display
XAUTHORITY=$xauthority
EOF
  fi

  if [ "$is_camera" = "1" ]; then
    read -rp "Camera-apparaat-index (leeg = standaardcamera) []: " camera_source
    cat >> "$ENV_FILE" <<EOF
CAMERA_SOURCE=$camera_source
EOF
  fi

  chmod 600 "$ENV_FILE"
  echo "Configuratie opgeslagen in $ENV_FILE"
else
  echo "Configuratiebestand bestaat al op $ENV_FILE, sla vragen over."
fi

# shellcheck disable=SC1090
source <(grep -E '^SPOOKREGIE_IS_(MIRROR|CAMERA)=' "$ENV_FILE")
is_mirror="${SPOOKREGIE_IS_MIRROR:-1}"
is_camera="${SPOOKREGIE_IS_CAMERA:-0}"

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

  if [ "$is_mirror" = "1" ]; then
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
    launchctl load "$AGENTS_DIR/nl.spookregie.mirror.plist"
  fi

  if [ "$is_camera" = "1" ]; then
    cat > "$AGENTS_DIR/nl.spookregie.camera.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>nl.spookregie.camera</string>
  <key>ProgramArguments</key>
  <array>
    <string>$LAUNCHER</string>
    <string>mirror_node.camera_server</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO_DIR</string>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF
    launchctl load "$AGENTS_DIR/nl.spookregie.camera.plist"
  fi

  # Alleen de restart-commando's van de rollen die dit apparaat ook echt
  # draait -- zie dezelfde overweging bij de Linux-tak hierboven.
  mirror_restart_env=""
  if [ "$is_mirror" = "1" ]; then
    mirror_restart_env="    <key>MIRROR_RESTART_COMMAND</key><string>launchctl kickstart -k gui/$(id -u)/nl.spookregie.mirror</string>
"
  fi
  camera_restart_env=""
  if [ "$is_camera" = "1" ]; then
    camera_restart_env="    <key>CAMERA_RESTART_COMMAND</key><string>launchctl kickstart -k gui/$(id -u)/nl.spookregie.camera</string>
"
  fi

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
${mirror_restart_env}${camera_restart_env}  </dict>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF

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
  if [ "$is_mirror" = "1" ] && command -v apt-get >/dev/null 2>&1; then
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

  if [ "$is_mirror" = "1" ]; then
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
  fi

  if [ "$is_camera" = "1" ]; then
    sudo tee /etc/systemd/system/spookregie-camera.service > /dev/null <<EOF
[Unit]
Description=Spookregie camera-server
After=network.target

[Service]
Type=simple
User=$INSTALL_USER
Group=$INSTALL_GROUP
WorkingDirectory=$REPO_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$REPO_DIR/.venv/bin/python -m mirror_node.camera_server
Restart=always

[Install]
WantedBy=multi-user.target
EOF
  fi

  # ponytail: het unprivileged serviceaccount (User=$INSTALL_USER hierboven)
  # kan zelf geen `systemctl restart` op een systemwide unit doen -- dat
  # vereist root/polkit, wat een non-interactive Type=simple service niet
  # kan geven. Deze sudoers-drop-in geeft alleen de vaste commando's die
  # voor de gekozen rol(len) nodig zijn (één of twee regels), zonder
  # argumentvrijheid, dus dit heropent niet de root-privesc die de vorige
  # beveiligingsfix (User=/Group=) juist sloot.
  if [ "$is_mirror" = "1" ] || [ "$is_camera" = "1" ]; then
    sudoers_rules=""
    if [ "$is_mirror" = "1" ]; then
      sudoers_rules="${sudoers_rules}$INSTALL_USER ALL=(root) NOPASSWD: /bin/systemctl restart spookregie-mirror
"
    fi
    if [ "$is_camera" = "1" ]; then
      sudoers_rules="${sudoers_rules}$INSTALL_USER ALL=(root) NOPASSWD: /bin/systemctl restart spookregie-camera
"
    fi
    printf '%s' "$sudoers_rules" | sudo tee /etc/sudoers.d/spookregie >/dev/null
    sudo chmod 440 /etc/sudoers.d/spookregie
  fi

  # Alleen de restart-commando's van de rollen die dit apparaat ook echt
  # draait -- een CAMERA_RESTART_COMMAND zonder bijbehorende sudoers-regel
  # (hierboven) zou elke update-cyclus met een permission-error mislukken.
  mirror_restart_env=""
  [ "$is_mirror" = "1" ] && mirror_restart_env='Environment="MIRROR_RESTART_COMMAND=sudo -n /bin/systemctl restart spookregie-mirror"
'
  camera_restart_env=""
  [ "$is_camera" = "1" ] && camera_restart_env='Environment="CAMERA_RESTART_COMMAND=sudo -n /bin/systemctl restart spookregie-camera"
'

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
${mirror_restart_env}${camera_restart_env}ExecStart=$REPO_DIR/.venv/bin/python -m mirror_node.agent
Restart=always

[Install]
WantedBy=multi-user.target
EOF

  sudo systemctl daemon-reload
  services_to_enable="spookregie-agent"
  [ "$is_mirror" = "1" ] && services_to_enable="$services_to_enable spookregie-mirror"
  [ "$is_camera" = "1" ] && services_to_enable="$services_to_enable spookregie-camera"
  # shellcheck disable=SC2086
  sudo systemctl enable --now $services_to_enable
  echo "systemd-services actief ($services_to_enable). Bekijk status met: systemctl status $services_to_enable"

else
  echo "Onbekend platform: $PLATFORM -- alleen macOS (Darwin) en Linux worden ondersteund."
  exit 1
fi

if [ "$is_mirror" = "1" ] && [ "$is_camera" = "1" ]; then
  echo "Let op: dit apparaat draait zowel mirror als camera. Als beide dezelfde fysieke camera gebruiken, koppel de mirror-source in de beheerpagina dan aan http://127.0.0.1:8080/stream (de lokale camera-server) i.p.v. de ruwe apparaat-index -- anders vechten beide processen om dezelfde camera."
fi

echo "== Installatie klaar. Ga naar de beheerpagina > Apparaten om dit apparaat aan een output te koppelen. =="
