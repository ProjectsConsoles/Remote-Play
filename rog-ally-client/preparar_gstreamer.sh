#!/bin/bash
# Arma la carpeta "gstreamer" que va junto a RemotePlay_Ally.exe (2026-09-18).
# No se instala nada en Windows: se extrae el MSI oficial (msiexec no funciona por
# SSH, por eso se hace en la Mac con msitools) y se recorta a los plugins que usa
# _streaming_gstreamer() en src/main_client.py.
#   brew install msitools
#   ./preparar_gstreamer.sh            -> deja ./gstreamer (~178 MB)
set -e
VER=1.26.11
MSI=gstreamer-1.0-msvc-x86_64-$VER.msi
BASE=https://gstreamer.freedesktop.org/data/pkg/windows/$VER/msvc
TMP=$(mktemp -d)
curl -sL -o "$TMP/$MSI" "$BASE/$MSI"
curl -sL -o "$TMP/$MSI.sha256sum" "$BASE/$MSI.sha256sum"
(cd "$TMP" && shasum -a 256 -c "$MSI.sha256sum")
msiextract -C "$TMP/out" "$TMP/$MSI" >/dev/null
SRC="$TMP/out/PFiles64/gstreamer/1.0/msvc_x86_64"
DST="$(pwd)/gstreamer"
rm -rf "$DST"
mkdir -p "$DST/lib/gstreamer-1.0" "$DST/libexec"
cp -R "$SRC/bin" "$DST/bin"
cp -R "$SRC/libexec/gstreamer-1.0" "$DST/libexec/"
for p in coreelements udp mpegtsdemux videoparsersbad d3d d3d11 d3d12 opus opusparse \
         audioconvert audioresample wasapi wasapi2 videoconvertscale typefindfunctions \
         playback autodetect app audiorate videorate; do
    cp "$SRC/lib/gstreamer-1.0/gst$p.dll" "$DST/lib/gstreamer-1.0/"
done
rm -rf "$TMP"
du -sh "$DST"
# Para copiarla a Windows: COPYFILE_DISABLE=1 tar --no-xattrs -czf gstreamer.tgz gstreamer
# (sin eso macOS mete archivos ._* basura).
