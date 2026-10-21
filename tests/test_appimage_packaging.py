from __future__ import annotations

import os
import pathlib
import subprocess

import pytest


REPO = pathlib.Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="AppImage packaging is POSIX-only"
)


def test_appdir_layout_wraps_the_existing_pyinstaller_payload(tmp_path: pathlib.Path):
    dist = tmp_path / "dist"
    payload = dist / "Ouroboros"
    payload.mkdir(parents=True)
    launcher = payload / "Ouroboros"
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    internal = payload / "_internal"
    internal.mkdir()
    (internal / "repo.bundle").write_bytes(b"bundle")
    (internal / "VERSION").write_text("6.96.2\n", encoding="utf-8")
    (internal / "linux-gtk").mkdir()
    (internal / "linux-gtk/manifest.json").write_text("{}\n", encoding="utf-8")
    embedded_python = internal / "python-standalone/bin/python3"
    embedded_python.parent.mkdir(parents=True)
    embedded_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    appdir = tmp_path / "Ouroboros.AppDir"
    env = os.environ.copy()
    env["OUROBOROS_DIST_DIR"] = str(dist)
    env["OUROBOROS_APPDIR"] = str(appdir)
    subprocess.run(
        ["bash", "scripts/build_appimage.sh", "--appdir-only"],
        cwd=REPO,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert (appdir / "AppRun").stat().st_mode & 0o111
    assert (appdir / "ouroboros.desktop").is_file()
    assert (appdir / "ouroboros.png").is_file()
    assert (appdir / "usr/lib/ouroboros/Ouroboros").is_file()
    assert (appdir / "usr/lib/ouroboros/_internal/repo.bundle").is_file()
    assert (
        appdir / "usr/lib/ouroboros/_internal/python-standalone/bin/python3"
    ).is_file()
    desktop = (appdir / "ouroboros.desktop").read_text(encoding="utf-8")
    assert "Exec=Ouroboros" in desktop
    assert "Icon=ouroboros" in desktop

    version = subprocess.run(
        [str(appdir / "AppRun"), "--version"],
        env={**os.environ, "APPDIR": str(appdir)},
        check=True,
        capture_output=True,
        text=True,
    )
    assert version.stdout.strip() == "Ouroboros 6.96.2"


def test_apprun_exposes_cli_without_writing_to_the_mount(tmp_path: pathlib.Path):
    appdir = tmp_path / "AppDir"
    cli = appdir / "usr/lib/ouroboros/bin/ouroboros"
    cli.parent.mkdir(parents=True)
    cli.write_text('#!/bin/sh\nprintf "%s\\n" "$OUROBOROS_BUNDLE_DIR"\n', encoding="utf-8")
    cli.chmod(0o755)
    launcher = appdir / "usr/lib/ouroboros/Ouroboros"
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    apprun = appdir / "AppRun"
    apprun.write_bytes((REPO / "packaging/appimage/AppRun").read_bytes())
    apprun.chmod(0o755)

    result = subprocess.run(
        [str(apprun), "--cli", "--help"],
        env={**os.environ, "APPDIR": str(appdir)},
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == str(appdir / "usr/lib/ouroboros/_internal")


@pytest.mark.parametrize(
    ("original_tmpdir", "payload_status"),
    [(None, 0), ("/caller/tmp", 37)],
)
def test_apprun_custodian_restores_environment_and_removes_private_runtime(
    tmp_path: pathlib.Path,
    original_tmpdir: str | None,
    payload_status: int,
):
    private_base = tmp_path / "ouroboros-appimage-runtime-test"
    appdir = private_base / "appimage_extracted_test"
    observed = tmp_path / "payload-environment.txt"
    launcher = appdir / "usr/lib/ouroboros/Ouroboros"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(
        "#!/bin/sh\n"
        "if [ \"${TMPDIR+x}\" = x ]; then value=set:$TMPDIR; else value=unset; fi\n"
        "if env | grep -q '^OUROBOROS_APPIMAGE_'; then exit 9; fi\n"
        "printf '%s\\n' \"$value\" > \"$OBSERVED_PATH\"\n"
        "exit \"$TEST_PAYLOAD_STATUS\"\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    apprun = appdir / "AppRun"
    apprun.write_bytes((REPO / "packaging/appimage/AppRun").read_bytes())
    apprun.chmod(0o755)
    env = {
        **os.environ,
        "APPDIR": str(appdir),
        "TMPDIR": str(private_base),
        "OUROBOROS_APPIMAGE_RESTORE_TMPDIR": "1",
        "OUROBOROS_APPIMAGE_ORIGINAL_TMPDIR_SET": "1" if original_tmpdir is not None else "0",
        "OUROBOROS_APPIMAGE_ORIGINAL_TMPDIR": original_tmpdir or "",
        "OBSERVED_PATH": str(observed),
        "TEST_PAYLOAD_STATUS": str(payload_status),
    }

    result = subprocess.run(
        [str(apprun)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == payload_status
    assert observed.read_text(encoding="utf-8").strip() == (
        f"set:{original_tmpdir}" if original_tmpdir is not None else "unset"
    )
    assert not appdir.exists()
    assert not private_base.exists()


def test_apprun_custodian_refuses_unrelated_private_runtime(tmp_path: pathlib.Path):
    private_base = tmp_path / "ouroboros-appimage-runtime-test"
    private_base.mkdir()
    sentinel = private_base / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    appdir = tmp_path / "elsewhere" / "appimage_extracted_test"
    launcher = appdir / "usr/lib/ouroboros/Ouroboros"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    apprun = appdir / "AppRun"
    apprun.write_bytes((REPO / "packaging/appimage/AppRun").read_bytes())
    apprun.chmod(0o755)

    result = subprocess.run(
        [str(apprun)],
        env={
            **os.environ,
            "APPDIR": str(appdir),
            "TMPDIR": str(private_base),
            "OUROBOROS_APPIMAGE_RESTORE_TMPDIR": "1",
            "OUROBOROS_APPIMAGE_ORIGINAL_TMPDIR_SET": "0",
            "OUROBOROS_APPIMAGE_ORIGINAL_TMPDIR": "",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "outside its private runtime root" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert appdir.is_dir()


def test_apprun_unmarked_desktop_path_keeps_exec_pid_and_appdir(tmp_path: pathlib.Path):
    appdir = tmp_path / "AppDir"
    pid_output = tmp_path / "launcher.pid"
    launcher = appdir / "usr/lib/ouroboros/Ouroboros"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$$\" > \"$PID_OUTPUT\"\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    apprun = appdir / "AppRun"
    apprun.write_bytes((REPO / "packaging/appimage/AppRun").read_bytes())
    apprun.chmod(0o755)

    process = subprocess.Popen(
        [str(apprun)],
        env={**os.environ, "APPDIR": str(appdir), "PID_OUTPUT": str(pid_output)},
    )
    process_pid = process.pid
    assert process.wait(timeout=10) == 0

    assert int(pid_output.read_text(encoding="utf-8")) == process_pid
    assert appdir.is_dir()


def test_appimage_builder_pins_tool_and_embedded_runtime():
    script = (REPO / "scripts/build_appimage.sh").read_text(encoding="utf-8")

    assert "RUNTIME_VERSION=20251108" in script
    assert "2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d" in script
    assert "00cbdfcf917cc6c0ff6d3347d59e0ca1f7f45a6df1a428a0d6d8a78664d87444" in script
    assert "releases/download/${RUNTIME_VERSION}/runtime-${TOOL_ARCH}" in script
    assert 'fetch_verified "$RUNTIME" "$RUNTIME_URL" "$RUNTIME_SHA256"' in script
    assert '"$TOOL" --runtime-file "$RUNTIME" "$APPDIR" "$OUTPUT"' in script


def test_appdir_refuses_payload_without_native_closure(tmp_path):
    payload = tmp_path / 'Ouroboros'
    payload.mkdir()
    (payload / 'Ouroboros').write_text('#!/bin/sh\nexit 0\n')
    (payload / 'Ouroboros').chmod(0o755)
    result = subprocess.run(['bash', 'scripts/build_appimage.sh', '--appdir-only'],
                            cwd=REPO, env={**os.environ, 'OUROBOROS_DIST_DIR': str(tmp_path)},
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert 'GTK/WebKit closure is missing' in result.stderr


def test_webkit_relocation_is_bounded_and_preserves_elf_offsets():
    import runpy

    relocate = runpy.run_path(str(REPO / 'scripts/bundle_linux_gtk.py'))['relocate_webkit']
    original = (b'\x7fELF\0/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1\0'
                b'/usr/share/webkitgtk-4.1\0/usr/bin/bwrap\0/usr/bin/xdg-dbus-proxy\0'
                b'/usr/libexec/webkit2gtk-4.1/WebKitWebProcess\0/usr/unrelated\0'
                b'/usr/lib/x86_64-linux-gnu/webkit2gtk-4.10\0'
                b'https://example.invalid/usr/bin/bwrap\0')
    changed, edits = relocate(original)
    assert len(changed) == len(original)
    assert b'././/lib/x86_64-linux-gnu/webkit2gtk-4.1\0' in changed
    assert b'/usr/unrelated\0' in changed
    assert b'/usr/lib/x86_64-linux-gnu/webkit2gtk-4.10\0' in changed
    assert b'https://example.invalid/usr/bin/bwrap\0' in changed
    assert b'././/libexec/webkit2gtk-4.1/WebKitWebProcess\0' in changed
    assert b'././/bin/xdg-dbus-proxy\0' in changed
    assert len(edits) == 5
    with pytest.raises(RuntimeError, match='sandbox helper paths changed'):
        relocate(original.replace(b'/usr/bin/bwrap', b'/unknown/bwrap'))
    with pytest.raises(RuntimeError, match='prefix changed'):
        relocate(b'\x7fELF\0/a/new/upstream/layout\0')


def test_desktop_bundle_environment_survives_exec_and_preserves_cli_cwd(tmp_path):
    appdir = tmp_path / 'AppDir'
    payload = appdir / 'usr/lib/ouroboros'
    root = payload / '_internal/linux-gtk'
    root.mkdir(parents=True)
    (root / 'manifest.json').write_text('{}')
    (root / 'desktop-env.sh').write_bytes((REPO / 'packaging/appimage/desktop-env.sh').read_bytes())
    apprun = appdir / 'AppRun'
    apprun.write_bytes((REPO / 'packaging/appimage/AppRun').read_bytes())
    apprun.chmod(0o755)
    successor = payload / 'successor'
    successor.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$PYWEBVIEW_GUI" "$LD_LIBRARY_PATH"\n')
    successor.chmod(0o755)
    launcher = payload / 'Ouroboros'
    launcher.write_text('#!/bin/sh\nexec "$OUROBOROS_BUNDLE_DIR/../successor"\n')
    launcher.chmod(0o755)
    env = {**os.environ, 'APPDIR': str(appdir), 'PYWEBVIEW_GUI': 'qt', 'LD_LIBRARY_PATH': '/caller/lib'}
    result = subprocess.run([str(apprun)], env=env, cwd=tmp_path, capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == [str(root), 'gtk', f'{payload}/_internal:{root}/lib/x86_64-linux-gnu:/caller/lib']
    cli = payload / 'bin/ouroboros'
    cli.parent.mkdir()
    cli.write_bytes(successor.read_bytes())
    cli.chmod(0o755)
    result = subprocess.run([str(apprun), '--cli'], env=env, cwd=tmp_path, capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == [str(tmp_path), 'qt', '/caller/lib']


def _typelib(dependencies=b'', libraries=b''):
    """A minimal format-4 typelib whose header fields 36/52 point at C strings."""
    import struct

    data = bytearray(b'GOBJ\nMETADATA\r\n\x1a' + bytes([4, 0]) + bytes(46))
    for field, value in ((36, dependencies), (52, libraries)):
        if value:
            struct.pack_into('<I', data, field, len(data))
            data += value + b'\0'
    return bytes(data)


def test_typelib_closure_refuses_dependencies_the_host_would_supply(tmp_path):
    import runpy

    bundle = runpy.run_path(str(REPO / 'scripts/bundle_linux_gtk.py'))
    requirements = bundle['typelib_requirements']
    assert requirements(_typelib(b'cairo-1.0|HarfBuzz-0.0|GObject-2.0', b'libpango-1.0.so.0')) == (
        ['cairo-1.0', 'HarfBuzz-0.0', 'GObject-2.0'], ['libpango-1.0.so.0'])
    assert requirements(_typelib()) == ([], [])
    with pytest.raises(RuntimeError, match='Unknown typelib format'):
        requirements(b'not a typelib' + bytes(64))
    (tmp_path / 'Pango-1.0.typelib').write_bytes(_typelib(b'HarfBuzz-0.0|GObject-2.0', b'libpango-1.0.so.0'))
    (tmp_path / 'GObject-2.0.typelib').write_bytes(_typelib(b'', b'libgobject-2.0.so.0'))
    with pytest.raises(RuntimeError, match=r"Pango-1\.0\.typelib requires typelibs outside the closure: \['HarfBuzz-0\.0'\]"):
        bundle['typelib_libraries'](tmp_path)
    (tmp_path / 'HarfBuzz-0.0.typelib').write_bytes(
        _typelib(b'GObject-2.0', b'libharfbuzz.so.0,libharfbuzz-gobject.so.0'))
    assert bundle['typelib_libraries'](tmp_path) == [
        ('GObject-2.0.typelib', 'libgobject-2.0.so.0'), ('HarfBuzz-0.0.typelib', 'libharfbuzz.so.0'),
        ('HarfBuzz-0.0.typelib', 'libharfbuzz-gobject.so.0'), ('Pango-1.0.typelib', 'libpango-1.0.so.0')]
    assert 'gir1.2-harfbuzz-0.0' in bundle['PACKAGES']


def test_gi_extension_takes_libpython_only_from_its_own_interpreter(tmp_path):
    import runpy

    linked = runpy.run_path(str(REPO / 'scripts/bundle_linux_gtk.py'))['linked_libraries']
    interpreter = tmp_path / 'python-standalone/lib'
    interpreter.mkdir(parents=True)
    ldd = ('\tlinux-vdso.so.1 (0x00007ffc)\n'
           '\tlibgirepository-1.0.so.1 => /lib/x86_64-linux-gnu/libgirepository-1.0.so.1 (0x00007f01)\n'
           '\tlibpython3.10.so.1.0 => {}\n'
           '\t/lib64/ld-linux-x86-64.so.2 (0x00007f02)\n')
    targets = ('not found', '/usr/lib/x86_64-linux-gnu/libpython3.10.so.1.0 (0x00007f03)')
    for target in targets:
        for supplier in (interpreter, None):
            with pytest.raises(RuntimeError, match='its interpreter does not ship'):
                linked('_gi.so', ldd.format(target), supplier)
    (interpreter / 'libpython3.10.so.1.0').write_bytes(b'')
    for target in targets:
        # The interpreter's own copy satisfies it; a builder libpython is never shipped.
        assert linked('_gi.so', ldd.format(target), interpreter) == [
            ('libgirepository-1.0.so.1', '/lib/x86_64-linux-gnu/libgirepository-1.0.so.1')]
    with pytest.raises(RuntimeError, match='Unresolved dependency'):
        linked('_gi.so', '\tlibffi.so.8 => not found\n', interpreter)
    with pytest.raises(RuntimeError, match='Unresolved dependency'):
        linked('_gi.so', "/x/_gi.so: /lib/x86_64-linux-gnu/libc.so.6: version `GLIBC_2.38' not found\n", interpreter)


def test_native_recipe_uses_only_the_signed_ordinary_archive():
    import re

    recipe = (REPO / 'packaging/appimage/native-qualification.Dockerfile').read_text()
    keyring = '[signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg]'
    assert re.findall(r"'(deb [^']*)'", recipe) == [
        f'deb {keyring} http://archive.ubuntu.com/ubuntu jammy main universe',
        f'deb {keyring} http://archive.ubuntu.com/ubuntu jammy-updates main universe',
        f'deb {keyring} http://security.ubuntu.com/ubuntu jammy-security main universe']
    for bypass in ('trusted=yes', 'allow-insecure', 'check-valid-until', 'AllowUnauthenticated', 'snapshot.ubuntu.com'):
        assert bypass not in recipe
    # apt-get source cannot fetch the image's superseded versions.
    assert recipe.index('dist-upgrade') < recipe.index('ca-certificates python3 git curl')
    builder = recipe.split('FROM common AS builder')[1].split('FROM common AS desktop')[0]
    release = (REPO / '.github/workflows/ci.yml').read_text().split('Install Linux GTK closure build inputs')[1]
    for install in (builder, release.split('- name:')[0]):
        assert 'libwebkit2gtk-4.1-dev gir1.2-webkit2-4.1' in install


def test_native_qualifier_records_webkit_sandbox_without_requiring_it():
    import ast
    import runpy

    script = REPO / 'scripts/qualify_linux_appimage.py'
    observe = runpy.run_path(str(script))['sandbox_observation']

    def process(pid, exe, namespace, **environment):
        return {'pid': pid, 'exe': exe, 'mount_namespace': namespace, 'environment': environment}

    helper = '/x/_internal/linux-gtk/lib/x86_64-linux-gnu/webkit2gtk-4.1/WebKitWebProcess'
    records = [process(1, '/x/python3', 'mnt:[1]'), process(2, helper, 'mnt:[1]'),
               process(3, '/x/_internal/linux-gtk/bin/bwrap', 'mnt:[2]', WEBKIT_FORCE_SANDBOX='1'),
               process(4, helper, 'mnt:[2]'),
               {'pid': 5, 'unreadable': 'denied', 'exe': '', 'maps': '', 'environment': {}}]
    assert observe(records, 'mnt:[1]') == {
        'launcher_mount_namespace': 'mnt:[1]',
        'web_processes': [{'pid': 2, 'mount_namespace': 'mnt:[1]', 'separate_mount_namespace': False},
                          {'pid': 4, 'mount_namespace': 'mnt:[2]', 'separate_mount_namespace': True}],
        'sandbox_helpers': ['bwrap'], 'webkit_sandbox_variables': ['WEBKIT_FORCE_SANDBOX']}
    asserts = [ast.unparse(node) for node in ast.walk(ast.parse(script.read_text())) if isinstance(node, ast.Assert)]
    assert asserts and not any('mount_namespace' in text or 'ns/mnt' in text for text in asserts)
