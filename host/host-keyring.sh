#!/bin/sh
# Runs as the guest's login user on its session bus. The offline image contains no credentials.
set -eu
umask 077
state="$HOME/.local/state/cindy-cloud-host"
mkdir -p "$state"
exec 9>"$state/keyring.lock"
flock 9
tmp=$(mktemp "$state/.secret.XXXXXX")
trap 'rm -f "$tmp"' EXIT
if [ ! -s "$state/keyring-password" ]; then
  openssl rand -hex 32 | tr -d '\n' > "$tmp"
  ln "$tmp" "$state/keyring-password"
fi
gnome-keyring-daemon --unlock --components=secrets 9>&- < "$state/keyring-password" >/dev/null
if secret-tool lookup application Cindy xdg:schema chrome_libsecret_os_crypt_password_v2 >/dev/null; then
  touch "$state/initialized"
  exit 0
fi
# Once initialized, a transient Secret Service failure must never replace the encryption key.
if [ -f "$state/initialized" ]; then exit 1; fi
openssl rand -base64 32 | tr -d '\n' | secret-tool store --label='Cindy Host' application Cindy xdg:schema chrome_libsecret_os_crypt_password_v2
secret-tool lookup application Cindy xdg:schema chrome_libsecret_os_crypt_password_v2 >/dev/null
touch "$state/initialized"
