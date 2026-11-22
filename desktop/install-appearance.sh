#!/usr/bin/env bash
# Seed the desktop appearance without replacing existing settings.
set -euo pipefail
appearance_dir="$(dirname -- "${BASH_SOURCE[0]}")/appearance"
cindy_launcher=${1:?Pass the installed Cindy .desktop file}
shared=/usr/local/share/cindy-cloud-desktop
install -d -m 755 /usr/share/backgrounds/cindy-cloud "$shared"
install -m 644 "$appearance_dir/cindy-whisper.jpg" /usr/share/backgrounds/cindy-cloud/
install -m 644 "$cindy_launcher" "$shared/cindy.desktop"
install -m 644 "$appearance_dir/"*.xml "$shared/"

runuser -u ubuntu -- bash -s -- "$shared" <<'SEED'
set -euo pipefail
umask 077
channels="$HOME/.config/xfce4/xfconf/xfce-perchannel-xml"
mkdir -p "$channels"
for channel in xfce4-desktop xfce4-panel xfwm4 xsettings; do
  if [[ ! -e "$channels/$channel.xml" ]]; then
    install -m 600 "$1/$channel.xml" "$channels/"
  fi
done
SEED
