# Cindy Cloud Images

Ubuntu 24.04 image recipes for two kinds of Cindy cloud computer.

| Image | What it runs | Where to customize it |
| --- | --- | --- |
| Host | Cindy Host as a systemd user service, with a per-instance credential store | [Host installer](host/prepare-host-image.py) and [keyring setup](host/host-keyring.sh) |
| Desktop | Cindy with XFCE, a virtual X11 display and Firefox | [Desktop installer and first-boot settings](desktop/install-desktop.sh) |

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

The installer prepares XFCE, Firefox, the credential store and the Cindy autostart entry. Shut down the builder after installation and mount its system disk on a separate Linux machine. On each provisioned guest, the deployment bootstrap calls `/usr/local/lib/cindy-cloud-desktop/activate` with the desired language, display size and timezone, for example `en-US 1920x1080 America/Los_Angeles`. The desktop session and Firefox use the guest user's systemd session bus.

## Seal and verify

For either edition, seal the **powered-off image** on the separate machine. Use a fresh build disk exclusively for this operation.

```sh
sudo python3 common/seal-offline-image.py --offline-root "$IMAGE_ROOT"
```

Sealing rejects known Cindy enrollment files, keyring state and Snap credentials. It clears builder identities, SSH host keys and cloud-init state so each new instance starts with its own identity. Unmount the sealed volume before snapshotting it. Boot a disposable clone to check Host enrollment or the desktop session and Firefox. Record the recipe commit and release digest with each published image in the deployment system.

## Local checks

Run `make test` with Bash, Make and Python 3.9+ on a development machine. The tests use temporary directories and require no cloud credentials. GitHub Actions runs the same checks on Ubuntu. Full installation and guest startup are separate image acceptance steps.

## Publication

Keep credentials, tenant configuration, private image identifiers, guest data, binary packages and disk images in their respective release or deployment systems. Before opening the repository, select a source license and review the distribution terms for any artifacts planned for publication.
