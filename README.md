# Cindy Cloud Images

Ubuntu 24.04 image recipes for two kinds of Cindy cloud computer.

| Image | What it runs | Where to customize it |
| --- | --- | --- |
| Host | Cindy Host as a systemd user service, with a per-instance credential store | [Host installer](host/prepare-host-image.py) and [keyring setup](host/host-keyring.sh) |
| Desktop | Cindy with XFCE, an authenticated X11 display, Chrome by default and Firefox | [Desktop installer and first-boot settings](desktop/install-desktop.sh) |

Both recipes assume a fresh Ubuntu image with an `ubuntu` user and systemd. Use a trusted Cindy Linux release that supports cloud enrollment and matches the architecture and service environment of the intended guests. Obtain its SHA-256 digest from the approved release record. The image repository contains build instructions and tests. The deployment service owns region-specific image IDs, billing and single-use guest enrollment.

For the shared monthly builder, renewal checks and regional image publication, see [builder maintenance](docs/builder-maintenance.md).

## Prepare a Host image

Install `dbus-user-session`, `gnome-keyring`, `libsecret-tools`, `openssl` and `util-linux` in the clean base image. Shut down the builder and mount its system disk on a separate Linux machine. Set `IMAGE_ROOT` to that mount, `HOST_RELEASE` to the unpacked release directory, and `INVENTORY_SHA256` to the digest of its `SHA256SUMS.json`. Match the edition (`cn` or `global`) and architecture (`x64` or `arm64`) to the release.

```sh
sudo python3 host/prepare-host-image.py "$HOST_RELEASE" \
  --root "$IMAGE_ROOT" --inventory-sha256 "$INVENTORY_SHA256" \
  --edition global --arch x64
```

The installer verifies the inventory and every listed file before installing the release and its service. The deployment bootstrap enables `cindy-cloud-host.service` for the guest after provisioning its enrollment material.

## Prepare a Desktop image

Run the following **on a fresh Ubuntu 24.04 build system**. Set `DESKTOP_DEB` to the installer path and `DEB_SHA256` to its approved digest. Image preparation changes SSH configuration and installs system packages. Use an out-of-band builder management channel.

```sh
sudo bash desktop/install-desktop.sh --prepare-image "$DEB_SHA256" "$DESKTOP_DEB"
```

The installer prepares XFCE, the credential store, Ubuntu desktop language packs (`en-US`, `zh-CN`, `zh-TW`, `ja-JP`, `ko-KR`, `de-DE`, `fr-FR`, `es-ES`, `pt-BR`, `pt-PT`) and the Cindy autostart entry. It installs Google Chrome Stable from Google's signed APT repository and sets the system default for web links. Firefox remains available, alongside a text editor, PDF viewer, archive manager and basic command-line tools. Shut down the builder after installation and mount its system disk on a separate Linux machine. On each provisioned guest, the deployment bootstrap calls `/usr/local/lib/cindy-cloud-desktop/activate` with the desired language, display size and timezone, for example `en-US 1920x1080 America/Los_Angeles`, writing session defaults and `/etc/default/locale` offline. Activation also turns on Cindy's install-updates-while-idle setting unless the guest user already chose otherwise; the image installs `pkexec` and a polkit rule so the desktop user's updates install without a password prompt. On its first boot each guest installs the newest official Cindy for the baked release's region before the desktop session starts Cindy, and keeps the baked release if the download or any check fails. The desktop session uses the guest user's systemd session bus.

Run the installer from a checkout so it can read [the XFCE defaults and wallpaper](desktop/appearance/README.md). New desktop profiles open with Cindy Whisper, dark window chrome and a bottom panel with Cindy, Chrome, Files and Terminal. Users can customize the appearance from XFCE Settings.

## Seal and verify

For either edition, seal the **powered-off image** on the separate machine. Use a fresh build disk exclusively for this operation.

```sh
sudo python3 common/seal-offline-image.py --offline-root "$IMAGE_ROOT"
```

Both images restrict sshd to `~ubuntu/.ssh/cindy-owner-authorized-keys`, which Cindy on the machine maintains for the owner's devices, and install a boot gate (`common/ssh_access_gate.py`) that holds a Cindy-written key list until Cindy has rechecked the device list. Sealing rejects known Cindy enrollment files, keyring state, browser profiles and Snap credentials. It clears builder identities, SSH host keys and cloud-init state so each new instance starts with its own identity. Unmount the sealed volume before snapshotting it. Use the [Cindy readiness checklist](docs/cindy-readiness.md) to validate disposable clones and record the release evidence.

## Local checks

Run `make test` with Bash, Make and Python 3.9+ on a development machine. The tests use temporary directories and require no cloud credentials. GitHub Actions runs the same checks on Ubuntu. Full installation and guest startup are separate image acceptance steps.

## Publication

Keep credentials, tenant configuration, private image identifiers, guest data, binary packages and disk images in their respective release or deployment systems. Before opening the repository, select a source license and review the distribution terms for any artifacts planned for publication.
