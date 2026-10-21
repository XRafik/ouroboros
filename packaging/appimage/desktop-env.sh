# Sourced by AppRun before the frozen loader, inherited by the source handoff.
# bundle_linux_gtk.py relocates WebKit's compiled /usr paths to ././ paths.
GTK_ROOT="$OUROBOROS_BUNDLE_DIR/linux-gtk"
export LD_LIBRARY_PATH="$OUROBOROS_BUNDLE_DIR:$GTK_ROOT/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
# Resource paths are set by desktop_media after PyInstaller's own GI hooks.
# A KDE session must still select the shipped GTK backend, not an ambient Qt.
export PYWEBVIEW_GUI=gtk
cd "$GTK_ROOT"
