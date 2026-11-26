#!/usr/bin/env bash
# Run as root on a fresh Ubuntu machine. The no-argument path installs and starts the desktop.
set -euo pipefail
desktop_dir="$(dirname -- "${BASH_SOURCE[0]}")"
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
ExposeAuthInfo yes
SSH
  # Cindy keeps the owner's device keys in that file; recheck them at boot before sshd lets anyone in.
  python3 "$desktop_dir/../common/ssh_access_gate.py" /
fi
id ubuntu >/dev/null
exec 9>/run/lock/cindy-cloud-desktop-install
flock 9
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
  xfce4 xfce4-terminal greybird-gtk-theme papirus-icon-theme \
  mousepad evince file-roller xdg-utils \
  dbus-x11 dbus-user-session libglib2.0-bin xauth xvfb x11-utils xclip xdotool \
  openssl gnome-keyring libsecret-tools at-spi2-core libxtst6 pkexec \
  curl jq ca-certificates gpg gpg-agent libgl1-mesa-dri \
  fonts-noto-cjk fonts-noto-color-emoji locales tzdata firefox \
  language-pack-en language-pack-gnome-en \
  language-pack-zh-hans language-pack-gnome-zh-hans \
  language-pack-zh-hant language-pack-gnome-zh-hant \
  language-pack-ja language-pack-gnome-ja \
  language-pack-ko language-pack-gnome-ko \
  language-pack-de language-pack-gnome-de \
  language-pack-fr language-pack-gnome-fr \
  language-pack-es language-pack-gnome-es \
  language-pack-pt language-pack-gnome-pt \
  git rsync ripgrep unzip zip
locale-gen en_US.UTF-8 zh_CN.UTF-8 zh_TW.UTF-8 ja_JP.UTF-8 ko_KR.UTF-8 \
  de_DE.UTF-8 fr_FR.UTF-8 es_ES.UTF-8 pt_BR.UTF-8 pt_PT.UTF-8
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
chmod 755 "$work"
chrome_home="$work/google-gnupg"
install -d -m 700 "$chrome_home"
curl --fail --silent --show-error --retry 3 \
  https://dl.google.com/linux/linux_signing_key.pub -o "$work/google.asc"
gpg --batch --homedir "$chrome_home" --import "$work/google.asc"
# Export only Google's active primary key and its signing subkeys.
google_key=EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796
gpg --batch --homedir "$chrome_home" --export "$google_key" > "$work/google-chrome.gpg"
test -s "$work/google-chrome.gpg"
install -d -m 755 /etc/apt/keyrings
install -m 644 "$work/google-chrome.gpg" /etc/apt/keyrings/cindy-google-chrome.gpg
cat >/etc/apt/sources.list.d/google-chrome.sources <<CHROME
Types: deb
URIs: https://dl.google.com/linux/chrome/deb/
Suites: stable
Components: main
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/cindy-google-chrome.gpg
CHROME
# The vendor's install hook otherwise adds its own APT source and key.
cat >/etc/default/google-chrome <<'CHROME'
repo_add_once="false"
repo_reenable_on_distupgrade="false"
CHROME
apt-get update -qq
apt-get install -y --no-install-recommends google-chrome-stable
dpkg-query -W -f='${Version}\n' google-chrome-stable > "$work/chrome.version"
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
# Cindy's updater replaces its system package through pkexec. The desktop user already has
# passwordless sudo on this machine, so let its pkexec requests through without an
# authentication agent; otherwise unattended updates stop at a password prompt nobody sees.
cat >"$work/cindy-update.rules" <<'POLKIT'
// Cindy cloud desktop: the desktop user already has passwordless sudo.
// Lets Cindy's updater run pkexec unattended so idle auto-install works.
polkit.addRule(function(action, subject) {
  if (action.id == "org.freedesktop.policykit.exec" && subject.user == "ubuntu") {
    return polkit.Result.YES;
  }
});
POLKIT
mkdir -p /etc/polkit-1/rules.d
install -o root -g root -m 644 "$work/cindy-update.rules" /etc/polkit-1/rules.d/49-cindy-cloud-desktop-update.rules
bash "$desktop_dir/install-appearance.sh" "/usr/share/applications/$package_name.desktop"
install -d -m 755 /usr/local/lib/cindy-cloud-desktop
install -m 644 "$work/chrome.version" /usr/local/lib/cindy-cloud-desktop/chrome.version
install -d -m 755 /etc/xdg/xfce4
cat >/etc/xdg/xfce-mimeapps.list <<'MIME'
[Default Applications]
x-scheme-handler/http=google-chrome.desktop;
x-scheme-handler/https=google-chrome.desktop;
text/html=google-chrome.desktop;
MIME
cat >/etc/xdg/xfce4/helpers.rc <<'XFCE'
WebBrowser=google-chrome
XFCE
cat >/usr/local/lib/cindy-cloud-desktop/session <<'SESSION'
#!/bin/bash
set -euo pipefail
umask 077
export XDG_SESSION_TYPE=x11 XDG_CURRENT_DESKTOP=XFCE DESKTOP_SESSION=xfce
# Enable GTK's AT-SPI bridge inside this authenticated desktop session.
export GTK_A11Y=atspi
unset NO_AT_BRIDGE
# D-Bus-activated desktop apps need the display, Xauthority, locale and timezone.
dbus-update-activation-environment --systemd DISPLAY XAUTHORITY \
  XDG_SESSION_TYPE XDG_CURRENT_DESKTOP DESKTOP_SESSION GTK_A11Y LANG LANGUAGE TZ
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
cat >/usr/local/lib/cindy-cloud-desktop/update <<'UPDATE'
#!/usr/bin/env bash
# First boot: install the newest official Cindy before the desktop session starts it, so a new
# machine neither opens an old release nor restarts into an update soon after. Any failure keeps
# the release baked into the image; Cindy's own updater installs later releases.
set -uo pipefail
state=/var/lib/cindy-cloud-desktop
build_info=/usr/lib/cindy/resources/linux-build-info
log() { printf 'cindy-cloud-desktop-update: %s\n' "$*"; }
# The desktop starts Cindy after 20 minutes at most. Replacing the package must never be cut short,
# so it only begins within the first 10 minutes: with the package lock wait (at most 5 minutes)
# it then ends well inside that window, and the unit's own time limit is only a backstop.
install_by=$(( $(date +%s) + 600 ))
install -d -m 755 "$state"
work=$(mktemp -d)
# The desktop session waits for this marker, so write it however the attempt ends.
trap 'rm -rf "$work"; touch "$state/update.done"' EXIT
trap 'exit 1' TERM INT
owner=$(dpkg-query -S "$build_info" 2>/dev/null) || { log 'Cindy is not installed from a system package'; exit 0; }
package=${owner%%:*}
case $package in cindy|cindydev) ;; *) log 'Unexpected Cindy package'; exit 0 ;; esac
mapfile -t build < "$build_info"
# Keep the region of the baked release: China and international builds use separate releases.
case ${build[3]:-} in
  cn) cdn=https://hotfix.cindy.com.cn/cindy ;;
  global) cdn=https://hotfix.cindy.app/cindy ;;
  *) log 'Unknown Cindy region'; exit 0 ;;
esac
debian_arch=$(dpkg --print-architecture)
case $debian_arch in amd64) arch=x64 ;; arm64) arch=arm64 ;; *) exit 0 ;; esac
installed=$(dpkg-query -W -f='${Version}' "$package")
fetch() {
  curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
    --retry 3 --connect-timeout 15 "$@"
}
fetch --max-time 60 "$cdn/manifest-linux-$arch.json" -o "$work/manifest" || { log 'Release manifest unavailable'; exit 0; }
version=$(jq -er '.app.version | select(test("^[0-9]+[.][0-9]+[.][0-9]+$"))' "$work/manifest") &&
  file=$(jq -er --arg arch "$arch" '.app.installer.file | select(test("^app/linux-" + $arch + "/[a-zA-Z0-9._-]+[.]deb$"))' "$work/manifest") &&
  hash=$(jq -er '.app.installer.sha256 | select(test("^[a-f0-9]{64}$"))' "$work/manifest") ||
  { log 'Unrecognized release manifest'; exit 0; }
if ! dpkg --compare-versions "$version" gt "$installed"; then
  log "Cindy $installed is current"
  exit 0
fi
# Abandon a stalled or late download instead of holding the desktop back.
budget=$(( install_by - $(date +%s) ))
(( budget >= 60 )) || { log 'No time left to download; keeping the baked release'; exit 0; }
fetch --retry 0 --max-time "$budget" --speed-limit 51200 --speed-time 60 "$cdn/$file" -o "$work/cindy.deb" ||
  { log 'Download failed'; exit 0; }
actual=$(sha256sum "$work/cindy.deb" | cut -d ' ' -f 1)
[[ $actual == "$hash" ]] || { log 'Digest mismatch'; exit 0; }
field() { dpkg-deb --field "$work/cindy.deb" "$1"; }
if [[ $(field Package) != "$package" || $(field Architecture) != "$debian_arch" || $(field Version) != "$version" ]]; then
  log 'Package does not match the release manifest'
  exit 0
fi
if (( $(date +%s) > install_by )); then
  log 'Too late to install before the desktop starts; keeping the baked release'
  exit 0
fi
# A first boot can still hold the package lock for automatic updates.
if ! DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=300 install -y --no-install-recommends \
  "$work/cindy.deb"; then
  # dpkg puts the old files back when unpacking fails. If it stopped while configuring instead,
  # finish that so the package is not left half installed.
  if [[ $(dpkg-query -W -f='${Status}' "$package") != 'install ok installed' ]]; then
    DEBIAN_FRONTEND=noninteractive dpkg --configure --pending
  fi
  log "Install failed; Cindy is $(dpkg-query -W -f='${Version} (${Status})' "$package")"
  exit 0
fi
log "Installed Cindy $version, replacing $installed"
UPDATE
chmod 755 /usr/local/lib/cindy-cloud-desktop/update
cat >/etc/systemd/system/cindy-cloud-desktop-update.service <<'UNIT'
[Unit]
Description=Install the newest Cindy before the first desktop session
Wants=network-online.target
After=network-online.target
ConditionPathExists=!/var/lib/cindy-cloud-desktop/update.done
[Service]
Type=oneshot
ExecStart=/usr/local/lib/cindy-cloud-desktop/update
TimeoutStartSec=30min
[Install]
WantedBy=multi-user.target
UNIT
systemctl enable cindy-cloud-desktop-update.service
cat >/usr/local/lib/cindy-cloud-desktop/start <<'START'
#!/usr/bin/env bash
set -euo pipefail
# On the first boot, start Cindy only after the newest release is installed (at most 20 minutes).
if [[ -f /etc/systemd/system/cindy-cloud-desktop-update.service ]]; then
  for _ in $(seq 600); do
    [[ -e /var/lib/cindy-cloud-desktop/update.done ]] && break
    sleep 2
  done
fi
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
  case $1 in
    en-US) lang=en_US.UTF-8; language=en_US:en ;;
    zh-CN) lang=zh_CN.UTF-8; language=zh_CN:zh ;;
    zh-TW) lang=zh_TW.UTF-8; language=zh_TW:zh ;;
    ja-JP) lang=ja_JP.UTF-8; language=ja_JP:ja ;;
    ko-KR) lang=ko_KR.UTF-8; language=ko_KR:ko ;;
    de-DE) lang=de_DE.UTF-8; language=de_DE:de ;;
    fr-FR) lang=fr_FR.UTF-8; language=fr_FR:fr ;;
    es-ES) lang=es_ES.UTF-8; language=es_ES:es ;;
    pt-BR) lang=pt_BR.UTF-8; language=pt_BR:pt ;;
    pt-PT) lang=pt_PT.UTF-8; language=pt_PT:pt ;;
    *) exit 2 ;;
  esac
  case $2 in 1600x1000|1920x1080) display=$2 ;; *) exit 2 ;; esac
  [[ $3 =~ ^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)*$ && -f /usr/share/zoneinfo/$3 ]] || exit 2
  defaults_dir=/etc/cindy-cloud-desktop
  locale_file=/etc/default/locale
  install -d -m 755 "$defaults_dir"
  defaults="$defaults_dir/defaults"
  pending=$(mktemp "$defaults_dir/.defaults.XXXXXX")
  trap 'rm -f "$pending"' EXIT
  printf 'LANG=%s\nLANGUAGE=%s\nCINDY_DISPLAY=%s\nTZ=%s\n' "$lang" "$language" "$display" "$3" >"$pending"
  chmod 644 "$pending"
  if ln "$pending" "$defaults" 2>/dev/null; then
    locale_dir=$(dirname -- "$locale_file")
    if [[ -d $locale_dir ]]; then
      locale_pending=$(mktemp "$locale_dir/.locale.XXXXXX")
      trap 'rm -f "$pending" "$locale_pending"' EXIT
      printf 'LANG=%s\nLANGUAGE=%s\n' "$lang" "$language" >"$locale_pending"
      chmod 644 "$locale_pending"
      mv -f "$locale_pending" "$locale_file"
    fi
  else
    cmp -s "$pending" "$defaults" || exit 1
  fi
fi
# Nobody sits at a cloud desktop to restart Cindy after an update, so the first boot turns on
# installing updates while idle. Written only when absent: the user's own choice always stays.
build_info=/usr/lib/cindy/resources/linux-build-info
if [[ -f $build_info ]]; then
  mapfile -t build < "$build_info"
  case ${build[3]:-} in
    cn) user_data=Cindy ;;
    global) user_data=CindyGlobal ;;
    *) user_data= ;;
  esac
  if [[ -n $user_data ]]; then
    runuser -u ubuntu -- bash -c 'umask 077 && set -C && cd "$2" && mkdir -p ".config/$1" &&
      { [[ -e ".config/$1/auto-update-settings.json" ]] ||
        printf "%s\n" "{\"autoRelaunchOnIdle\": true}" > ".config/$1/auto-update-settings.json"; }' _ "$user_data" ~ubuntu
  fi
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
  systemctl start --no-block cindy-cloud-desktop-update.service
  /usr/local/lib/cindy-cloud-desktop/activate
fi
