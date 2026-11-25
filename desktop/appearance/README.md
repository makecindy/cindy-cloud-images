# Cindy cloud desktop appearance

- `cindy-whisper.jpg` is a 2560 × 1440 export of [Cindy Whisper](https://github.com/makecindy/cindy/blob/931af69602/apps/desktop/src/renderer/assets/wallpapers/cindy-whisper.webp). It ships with the image and is available on the first boot offline.
- `xsettings.xml` and `xfwm4.xml` set the Greybird-dark theme and the Papirus-Dark icon theme. The panel uses the Cindy icon from the installed Linux package.
- `xfce4-desktop.xml` sets the backdrop for the Xvfb display. `xfce4-panel.xml` defines the default XFCE panel and pinned applications.

Build with the whole `desktop/` directory. Keep machine and user settings out of these defaults. Test both supported display sizes on a fresh profile before publishing an image.
