#!/usr/bin/env bash
# Run as root on a fresh Ubuntu machine. The no-argument path installs and starts the desktop.
set -euo pipefail
prepare_only=false
if [[ $# -ne 0 ]]; then
  if [[ $# -lt 2 || $# -gt 3 || $1 != --prepare-image || ! $2 =~ ^[a-f0-9]{64}$ ]]; then
    echo 'Usage: install-desktop.sh [--prepare-image EXPECTED_DEB_SHA256 [LOCAL_DEB]]' >&2
    exit 2
  fi
  prepare_only=true
fi
. /etc/os-release
[[ $ID = ubuntu && $VERSION_ID = 24.04 ]]
case $(dpkg --print-architecture) in
  amd64) arch=x64 ;;
  arm64) arch=arm64 ;;
  *) echo 'Unsupported package architecture' >&2; exit 1 ;;
esac
if $prepare_only; then
  install -d -m 755 /etc/ssh/sshd_config.d
  cat >/etc/ssh/sshd_config.d/00-cindy-cloud-owner.conf <<'SSH'
AuthorizedKeysFile .ssh/cindy-owner-authorized-keys
AuthorizedKeysCommand none
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
SSH
fi
id ubuntu >/dev/null
exec 9>/run/lock/cindy-cloud-desktop-install
flock 9
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends xfce4 xfce4-terminal dbus-x11 dbus-user-session xauth xvfb x11-utils openssl gnome-keyring libsecret-tools at-spi2-core curl jq ca-certificates libgl1-mesa-dri fonts-noto-cjk locales tzdata firefox
locale-gen en_US.UTF-8 zh_CN.UTF-8
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
chmod 755 "$work"
if [[ $prepare_only = true && $# -eq 3 ]]; then
  hash=$2
  install -m 644 -- "$3" "$work/cindy.deb"
else
  cdn=https://hotfix.cindy.app/cindy
  curl --fail --silent --show-error --retry 3 "$cdn/manifest-linux-$arch.json" -o "$work/manifest"
  file=$(jq -er --arg arch "$arch" '.app.installer.file | select(test("^app/linux-" + $arch + "/[a-zA-Z0-9._-]+[.]deb$"))' "$work/manifest")
  hash=$(jq -er '.app.installer.sha256 | select(test("^[a-f0-9]{64}$"))' "$work/manifest")
  if [[ $prepare_only = true && $hash != "$2" ]]; then
    echo 'Release digest differs from the image build input' >&2
    exit 1
  fi
  curl --fail --silent --show-error --retry 3 "$cdn/$file" -o "$work/cindy.deb"
fi
echo "$hash  $work/cindy.deb" | sha256sum --check --status
package_name=$(dpkg-deb --field "$work/cindy.deb" Package)
case $package_name in cindy|cindydev) ;; *) echo 'Unexpected Cindy desktop package' >&2; exit 1 ;; esac
apt-get install -y "$work/cindy.deb"
install -d -m 755 /usr/local/lib/cindy-cloud-desktop
cat >/usr/local/lib/cindy-cloud-desktop/session <<'SESSION'
#!/bin/bash
set -euo pipefail
umask 077
export XDG_SESSION_TYPE=x11 XDG_CURRENT_DESKTOP=XFCE DESKTOP_SESSION=xfce
state="$HOME/.local/state/cindy-cloud-desktop"
mkdir -p "$state"
# Generated separately on every machine. Store beside the desktop user's private state.
if [[ ! -s "$state/keyring-secret" ]]; then
  openssl rand -hex 32 | tr -d '\n' > "$state/keyring-secret.new"
  mv "$state/keyring-secret.new" "$state/keyring-secret"
fi
eval "$(gnome-keyring-daemon --unlock --components=secrets < "$state/keyring-secret")"
export GNOME_KEYRING_CONTROL
exec startxfce4
SESSION
chmod 755 /usr/local/lib/cindy-cloud-desktop/session
cat >/usr/local/lib/cindy-cloud-desktop/start <<'START'
#!/usr/bin/env bash
set -euo pipefail
# Snap applications ask the user's systemd manager to create a scope on this bus.
export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR:?}/bus"
exec /usr/bin/xvfb-run --auto-servernum --server-args="-screen 0 ${CINDY_DISPLAY:-1600x1000}x24 -nolisten tcp" /usr/local/lib/cindy-cloud-desktop/session
START
chmod 755 /usr/local/lib/cindy-cloud-desktop/start
install -d -m 755 /etc/systemd/user
cat >/etc/systemd/user/cindy-cloud-desktop.service <<'UNIT'
[Unit]
Description=Cindy cloud desktop
ConditionUser=ubuntu
[Service]
EnvironmentFile=-/etc/cindy-cloud-desktop/defaults
ExecStart=/usr/local/lib/cindy-cloud-desktop/start
Restart=always
RestartSec=5
[Install]
WantedBy=default.target
UNIT
install -d -o ubuntu -g ubuntu -m 700 ~ubuntu/.config ~ubuntu/.config/autostart
install -o ubuntu -g ubuntu -m 644 "/usr/share/applications/$package_name.desktop" ~ubuntu/.config/autostart/cindy.desktop
# Installed in both paths so a clean image can activate without a package repository or CDN.
cat >/usr/local/lib/cindy-cloud-desktop/activate <<'ACTIVATE'
#!/usr/bin/env bash
set -euo pipefail
# Only the first boot writes defaults. Retrying activation preserves the user's environment.
if [[ $# -ne 0 ]]; then
  [[ $# -eq 3 ]] || exit 2
  case $1 in zh-CN) lang=zh_CN.UTF-8 ;; en-US) lang=en_US.UTF-8 ;; *) exit 2 ;; esac
  case $2 in 1600x1000|1920x1080) display=$2 ;; *) exit 2 ;; esac
  [[ $3 =~ ^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)*$ && -f /usr/share/zoneinfo/$3 ]] || exit 2
  install -d -m 755 /etc/cindy-cloud-desktop
  defaults=/etc/cindy-cloud-desktop/defaults
  pending=$(mktemp /etc/cindy-cloud-desktop/.defaults.XXXXXX)
  trap 'rm -f "$pending"' EXIT
  printf 'LANG=%s\nCINDY_DISPLAY=%s\nTZ=%s\n' "$lang" "$display" "$3" >"$pending"
  chmod 644 "$pending"
  ln "$pending" "$defaults" 2>/dev/null || cmp -s "$pending" "$defaults" || exit 1
fi
loginctl enable-linger ubuntu
uid=$(id -u ubuntu)
systemctl start "user@$uid.service"
as_user=(runuser -u ubuntu -- env "XDG_RUNTIME_DIR=/run/user/$uid")
"${as_user[@]}" systemctl --user daemon-reload
"${as_user[@]}" systemctl --user --no-block enable --now cindy-cloud-desktop.service
ACTIVATE
chmod 755 /usr/local/lib/cindy-cloud-desktop/activate
if $prepare_only && compgen -G '/var/lib/snapd/device/private-keys-v1/*' >/dev/null; then
  # Firefox on Ubuntu is a snap. Keep the packages and let each clone register itself.
  jq -e '(.data.auth.users // []) | length == 0' /var/lib/snapd/state.json >/dev/null
  curl --noproxy '*' --unix-socket /run/snapd.socket --fail --silent --show-error --max-time 30 \
    -H 'Content-Type: application/json' --data '{"action":"forget","no-registration-until-reboot":true}' \
    http://localhost/v2/model/serial | jq -e '."status-code" == 200' >/dev/null
fi
printf '%s\n' "$hash" >/usr/local/lib/cindy-cloud-desktop/installer.sha256
if [[ $prepare_only = false ]]; then
  /usr/local/lib/cindy-cloud-desktop/activate
fi
