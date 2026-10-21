#!/usr/bin/env python3
"""#1297 research only. Native Windows x64, Python 3.11+, standard library.

JSON lines on stdout; exit 0 PASS, 1 FAIL, 2 NOT_RUN, 3 INCOMPLETE (any SKIP).
See PROBE.md before running. No imports from, or changes to, the application.
"""

import argparse
import contextlib
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import platform
import select
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid


RPE = 0xC000050B  # STATUS_REPARSE_POINT_ENCOUNTERED
MISSING = 0xC0000034  # STATUS_OBJECT_NAME_NOT_FOUND
NOT_DIR = 0xC0000103
IS_DIR = 0xC00000BA
GOOD = b"1297 confined bytes\x00\xff\r\n"
BAD = b"1297 OUTSIDE -- must never be returned"


def emit(event, **fields):
    print(json.dumps(dict(event=event, **fields), sort_keys=True), flush=True)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


class Skip(Exception):
    pass


class NtError(Exception):
    def __init__(self, operation, status):
        self.status = status & 0xFFFFFFFF
        super().__init__(f"{operation}: NTSTATUS 0x{self.status:08X}")


def segments(relative):
    """Probe grammar, not a proposed product selector. No filesystem calls."""
    if not isinstance(relative, str):
        raise ValueError("path must be text")
    parts = relative.split("/")
    devices = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    devices |= {p + n for p in ("COM", "LPT") for n in "0123456789¹²³"}
    for name in parts:
        if (not name or name in (".", "..") or name[-1] in ". "
                or any(ord(c) < 32 or c in '<>:"\\|?*' for c in name)
                or name.split(".", 1)[0].rstrip().upper() in devices
                or len(name.encode("utf-16-le")) > 510):
            raise ValueError("not a plain relative component")
    return parts


class Handle:
    def __init__(self, api, value):
        self.api, self.value = api, value
        api.live.add(value)

    def close(self):
        if self.value is not None:
            value, self.value = self.value, None
            self.api.live.remove(value)
            if not self.api.close_handle(value):
                raise C.WinError(C.get_last_error())

    def detach(self):
        value, self.value = self.value, None
        self.api.live.remove(value)
        return value

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Win:
    """Explicit x64 ABI. All descendant opens use the same candidate flags."""
    def __init__(self):
        from ctypes import wintypes as W
        self.live, self.opens = set(), 0
        H, U, P = W.HANDLE, C.c_uint32, C.c_void_p

        class Unicode(C.Structure):
            _fields_ = [("Length", C.c_uint16), ("MaximumLength", C.c_uint16),
                        ("Buffer", P)]

        class Attrs(C.Structure):
            _fields_ = [("Length", U), ("RootDirectory", H),
                        ("ObjectName", C.POINTER(Unicode)), ("Attributes", U),
                        ("SecurityDescriptor", P), ("SecurityQualityOfService", P)]

        class StatusUnion(C.Union):
            _fields_ = [("Status", C.c_int32), ("Pointer", P)]

        class IOSB(C.Structure):
            _fields_ = [("u", StatusUnion), ("Information", C.c_size_t)]

        class Info(C.Structure):
            _fields_ = [("attributes", U), ("times", U * 6), ("volume", U),
                        ("size_high", U), ("size_low", U), ("links", U),
                        ("index_high", U), ("index_low", U)]

        self.Unicode, self.Attrs, self.IOSB, self.Info = Unicode, Attrs, IOSB, Info
        check(C.sizeof(P) == 8 and C.sizeof(C.c_wchar) == 2, "requires Windows x64 ABI")
        check((C.sizeof(Unicode), C.sizeof(Attrs), C.sizeof(IOSB), C.sizeof(Info))
              == (16, 48, 16, 52), "unexpected ABI sizes")
        check(Attrs.RootDirectory.offset == 8 and IOSB.Information.offset == 8,
              "unexpected ABI offsets")
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self.nt = C.WinDLL("ntdll", use_last_error=True)

        def bind(dll, name, result, args):
            fn = getattr(dll, name)
            fn.restype, fn.argtypes = result, args
            return fn

        self.create = bind(self.kernel, "CreateFileW", H,
                           [W.LPCWSTR, U, U, P, U, U, H])
        self.close_handle = bind(self.kernel, "CloseHandle", W.BOOL, [H])
        self.info_call = bind(self.kernel, "GetFileInformationByHandle", W.BOOL,
                              [H, C.POINTER(Info)])
        self.file_type = bind(self.kernel, "GetFileType", U, [H])
        self.ntcreate = bind(self.nt, "NtCreateFile", C.c_int32,
                             [C.POINTER(H), U, C.POINTER(Attrs), C.POINTER(IOSB),
                              P, U, U, U, U, P, U])
        self.query = bind(self.nt, "NtQueryDirectoryFile", C.c_int32,
                          [H, H, P, P, C.POINTER(IOSB), P, U, U,
                           C.c_ubyte, P, C.c_ubyte])
        self.ioctl = bind(self.kernel, "DeviceIoControl", W.BOOL,
                          [H, U, P, U, P, U, C.POINTER(U), P])
        self.symlink_call = bind(self.kernel, "CreateSymbolicLinkW", C.c_ubyte,
                                 [W.LPCWSTR, W.LPCWSTR, U])
        self.pipe_create = bind(self.kernel, "CreateNamedPipeW", H,
                                [W.LPCWSTR, U, U, U, U, U, U, P])
        self.pipe_connect = bind(self.kernel, "ConnectNamedPipe", W.BOOL, [H, P])
        self.pipe_disconnect = bind(self.kernel, "DisconnectNamedPipe", W.BOOL, [H])
        self.volume = bind(self.kernel, "GetVolumeInformationByHandleW", W.BOOL,
                           [H, W.LPWSTR, U, C.POINTER(U), C.POINTER(U),
                            C.POINTER(U), W.LPWSTR, U])

    def owned(self, value):
        if value in (None, C.c_void_p(-1).value):
            raise C.WinError(C.get_last_error())
        return Handle(self, value)

    def trusted_root(self, path):
        # ONLY host-selected local fixture paths enter here. Follow a legitimate
        # owner-selected root junction; never reuse this for a task selector.
        h = self.owned(self.create(str(path), 0x100081, 7, None, 3, 0x02000000, None))
        try:
            self.require(h, directory=True)
            return h
        except BaseException:
            h.close()
            raise

    def info(self, h):
        info = self.Info()
        if not self.info_call(h.value, C.byref(info)):
            raise C.WinError(C.get_last_error())
        return info

    def identity(self, h):
        info = self.info(h)
        return [info.volume, info.index_high, info.index_low]

    def require(self, h, directory):
        check(self.file_type(h.value) == 1, "not FILE_TYPE_DISK")
        info = self.info(h)
        check(not info.attributes & 0x400, "returned a reparse handle")
        check(bool(info.attributes & 0x10) == directory, "wrong object type")

    def at(self, parent, name, directory):
        check(segments(name) == [name], "at() requires exactly one plain name")
        buf = C.create_unicode_buffer(name)
        length = len(name.encode("utf-16-le"))
        text = self.Unicode(length, length + 2, C.cast(buf, C.c_void_p))
        attrs = self.Attrs(C.sizeof(self.Attrs), parent.value, C.pointer(text),
                           0x1040, None, None)  # CASE_INSENSITIVE | DONT_REPARSE
        out, iosb = C.c_void_p(), self.IOSB()
        # SYNCHRONIZE | READ_ATTRIBUTES | READ_DATA (same bit as LIST_DIRECTORY).
        # Share read/write/delete deliberately permits the controlled swap cases.
        # FILE_OPEN; SYNCHRONOUS_IO_NONALERT | DIRECTORY/NON_DIRECTORY_FILE.
        self.opens += 1
        status = self.ntcreate(C.byref(out), 0x100081, C.byref(attrs), C.byref(iosb),
                               None, 0, 7, 1, 0x20 | (1 if directory else 0x40), None, 0)
        if status != 0:
            # No fallback on unsupported flags, sharing violations, or any other status.
            if status >= 0 and out.value not in (None, C.c_void_p(-1).value):
                self.owned(out.value).close()
            raise NtError("NtCreateFile", status)
        h = self.owned(out.value)
        try:
            check(iosb.u.Status == 0, "unexpected IO_STATUS_BLOCK completion")
            self.require(h, directory)
            return h
        except BaseException:
            h.close()
            raise

    def read_handle(self, h):
        import msvcrt
        # open_osfhandle transfers ownership on success only. h remains the owner
        # on conversion failure; after conversion the CRT descriptor is the owner.
        fd = msvcrt.open_osfhandle(h.value, os.O_RDONLY | os.O_BINARY)
        h.detach()
        try:
            check(stat.S_ISREG(os.fstat(fd).st_mode), "CRT fd is not regular")
            with os.fdopen(fd, "rb") as stream:
                fd = None
                return stream.read(4096)  # Every probe file is smaller than this.
        finally:
            if fd is not None:
                os.close(fd)

    def read(self, root, relative):
        parts = segments(relative)  # Validate the ENTIRE input before any open.
        with contextlib.ExitStack() as stack:
            parent = root
            for name in parts[:-1]:
                parent = stack.enter_context(self.at(parent, name, True))
            h = stack.enter_context(self.at(parent, parts[-1], False))
            return self.read_handle(h)

    def names(self, directory):
        names, restart = [], True
        while True:
            buf, iosb = C.create_string_buffer(65536), self.IOSB()
            status = self.query(directory.value, None, None, None, C.byref(iosb),
                                buf, len(buf), 12, 0, None, restart)
            restart = False  # FileNamesInformation; enumerate the HELD directory.
            if status & 0xFFFFFFFF == 0x80000006:  # STATUS_NO_MORE_FILES
                return sorted(n for n in names if n not in (".", ".."))
            if status != 0:
                raise NtError("NtQueryDirectoryFile", status)
            data, offset = buf.raw[:iosb.Information], 0
            check(bool(data), "empty successful enumeration")
            while True:
                check(offset + 12 <= len(data), "truncated FILE_NAMES_INFORMATION")
                next_offset, _, length = struct.unpack_from("<III", data, offset)
                check(length % 2 == 0 and offset + 12 + length <= len(data), "bad name length")
                names.append(data[offset + 12:offset + 12 + length].decode("utf-16-le"))
                if not next_offset:
                    break
                check(next_offset >= 12 + length, "bad enumeration offset")
                offset += next_offset

    def reparse_io(self, path, code, data=b""):
        # Fixture creation/inspection only: OPEN_REPARSE_POINT never follows it.
        setting = code == 0x900A4  # FSCTL_SET_REPARSE_POINT
        check((setting and bool(data)) or (code == 0x900A8 and not data),
              "expected SET with input or GET without input")
        with self.owned(self.create(str(path), 0x40000000 if data else 0,
                                   7, None, 3, 0x02200000, None)) as h:
            # SET has no output buffer. GET returns the reparse data for verification.
            output = None if setting else C.create_string_buffer(16384)
            output_size = 0 if setting else len(output)
            used = C.c_uint32()  # Required for synchronous DeviceIoControl, even SET.
            payload = C.create_string_buffer(data) if data else None
            if not self.ioctl(h.value, code, payload, len(data), output, output_size,
                              C.byref(used), None):
                error = C.get_last_error()
                emit("fixture_error", operation="FSCTL_SET_REPARSE_POINT" if setting
                     else "FSCTL_GET_REPARSE_POINT", path=str(path), winerror=error,
                     input_bytes=len(data), output_bytes=output_size)
                raise C.WinError(error)
            return b"" if setting else output.raw[:used.value]

    def junction(self, path, target, existing=False):
        if not existing:
            path.mkdir()
        substitute = ("\\??\\" + str(target)).encode("utf-16-le")
        display = str(target).encode("utf-16-le")
        body = struct.pack("<HHHH", 0, len(substitute), len(substitute) + 2, len(display))
        body += substitute + b"\0\0" + display + b"\0\0"
        data = struct.pack("<IHH", 0xA0000003, len(body), 0) + body
        self.reparse_io(path, 0x900A4, data)  # FSCTL_SET_REPARSE_POINT
        check(self.reparse_io(path, 0x900A8) == data, "junction fixture did not round trip")

    def symlink(self, path, target, directory=False):
        if not self.symlink_call(str(path), str(target), 2 | int(directory)):
            error = C.get_last_error()
            if error in (5, 1314):
                raise Skip(f"symlink creation requires rights/Developer Mode: winerror={error}")
            raise C.WinError(error)
        data = self.reparse_io(path, 0x900A8)
        check(struct.unpack_from("<I", data)[0] == 0xA000000C, "not a symlink fixture")
        offset, length, _, _, flags = struct.unpack_from("<HHHHI", data, 8)
        stored = data[20 + offset:20 + offset + length].decode("utf-16-le")
        target = str(target)
        if target.startswith("\\\\.\\"):
            expected = "\\??\\" + target[4:]
        elif target.startswith("\\\\"):
            expected = "\\??\\UNC\\" + target[2:]
        else:
            expected = "\\??\\" + target
        check(flags == 0 and stored == expected, "symlink target did not round trip")


def denied(operation, expected):
    try:
        value = operation()
    except NtError as exc:
        check(exc.status in expected, f"unexpected refusal, not proof: {exc}")
        return f"0x{exc.status:08X}"
    if isinstance(value, Handle):
        value.close()
    raise AssertionError("operation succeeded; required native refusal")


class LoopbackObserver:
    """No SMB server: exclusive sink ports, plus positively calibrated SYN capture.

    Some Windows configurations cannot capture loopback with SIO_RCVALL. Such a
    run MUST SKIP the UNC case. Accepted connections alone are not the oracle.
    """
    @staticmethod
    def setup(stage, operation, **fields):
        # An unavailable fixture says nothing about native no-contact support.
        emit("unc_setup", stage=stage, status="START", **fields)
        try:
            result = operation()
        except OSError as exc:
            emit("unc_setup", stage=stage, status="UNAVAILABLE", errno=exc.errno,
                 winerror=getattr(exc, "winerror", None), error=str(exc), **fields)
            raise Skip(f"UNC setup {stage} {fields}: {exc}") from exc
        emit("unc_setup", stage=stage, status="READY", **fields)
        return result

    def __enter__(self):
        self.stack = contextlib.ExitStack()
        try:
            self.listeners = []
            for port in (445, 139):
                listener = self.stack.enter_context(self.setup("sink_socket", socket.socket, port=port))
                self.setup("sink_exclusive", lambda: listener.setsockopt(
                    socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1), port=port)
                self.setup("sink_bind", lambda: listener.bind(("127.0.0.1", port)), port=port)
                self.setup("sink_listen", lambda: listener.listen(8), port=port)
                self.listeners.append(listener)
            self.raw = self.stack.enter_context(self.setup("raw_socket", lambda: socket.socket(
                socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)))
            self.setup("raw_bind", lambda: self.raw.bind(("127.0.0.1", 0)))
            self.setup("raw_rcvall_on", lambda: self.raw.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON))
            self.stack.callback(self.raw.ioctl, socket.SIO_RCVALL, socket.RCVALL_OFF)
            for port in (445, 139):
                with self.setup("tcp_control_connect", lambda: socket.create_connection(
                        ("127.0.0.1", port), timeout=2), port=port):
                    pass  # plain TCP only, sends no SMB request or credentials
            calibration = self.setup("tcp_control_observe", lambda: self.observe(1.0))
            emit("unc_calibration", phase="plain_tcp", observed=calibration)
            if set(calibration["syn_ports"]) != {445, 139} or calibration["connections"] != 2:
                raise Skip(f"loopback packet observer did not calibrate: {calibration}")
            self.calibration = calibration
            return self
        except BaseException:
            self.stack.close()
            raise

    def observe(self, seconds):
        ports, connections = [], 0
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            ready, _, _ = select.select([self.raw, *self.listeners], [], [],
                                        max(0, end - time.monotonic()))
            for sock in ready:
                if sock is not self.raw:
                    connection, _ = sock.accept()
                    connection.close()  # never sends a challenge or impersonates
                    connections += 1
                    continue
                packet = self.raw.recv(65535)
                if len(packet) < 40 or packet[0] >> 4 != 4 or packet[9] != 6:
                    continue
                offset = (packet[0] & 15) * 4
                if len(packet) < offset + 20 or packet[16:20] != b"\x7f\0\0\x01":
                    continue
                port = struct.unpack_from("!H", packet, offset + 2)[0]
                if port in (445, 139) and packet[offset + 13] & 2:
                    ports.append(port)  # SYN includes failed connection attempts.
        return dict(syn_ports=ports, connections=connections)

    def __exit__(self, *_):
        self.stack.close()


def cases(api, base, run):
    root, outside = base / "root", base / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "nested").mkdir()
    (root / "nested" / "bytes.bin").write_bytes(GOOD)
    (root / "direct.bin").write_bytes(GOOD)
    (outside / "bytes.bin").write_bytes(BAD)
    (outside / "escape.bin").write_bytes(BAD)

    with api.trusted_root(root) as held:
        fs, serial, maximum, flags = C.create_unicode_buffer(64), C.c_uint32(), C.c_uint32(), C.c_uint32()
        if not api.volume(held.value, None, 0, C.byref(serial), C.byref(maximum),
                          C.byref(flags), fs, len(fs)):
            raise C.WinError(C.get_last_error())
        emit("environment", filesystem=fs.value, root_identity=api.identity(held),
             attributes="OBJ_CASE_INSENSITIVE|OBJ_DONT_REPARSE (0x1040)",
             options_directory="0x21", options_file="0x60", share_access=7)
        if fs.value != "NTFS":
            raise Skip(f"this probe requires local NTFS, got {fs.value}")

        def positive():
            for name in ("direct.bin", "nested/bytes.bin"):
                check(api.read(held, name) == GOOD, "positive byte mismatch")
            with api.at(held, "nested", True) as directory:
                check(api.names(directory) == ["bytes.bin"], "directory enumeration mismatch")
            return dict(bytes=len(GOOD), sha256=hashlib.sha256(GOOD).hexdigest())

        if not run("positive_bytes_and_enumeration", positive):
            return  # Negative refusals are meaningless without working positive calls.

        def grammar():
            bad = ["", "/x", "a//b", ".", "..", "a/../b", "a\\b", "C:x", "C:/x",
                   "//127.0.0.1/probe/x", r"\\127.0.0.1\probe\x", r"\\?\C:\x",
                   r"\??\C:\x", r"\\.\pipe\probe", "x:stream", "NUL", "COM1.txt",
                   "LPT¹", "x.", "x ", "x\0y", "a/*"]
            before = api.opens
            for text in bad:
                try:
                    api.read(held, text)
                except ValueError:
                    continue
                raise AssertionError(f"accepted invalid selector {text!r}")
            check(api.opens == before, "invalid selector reached NtCreateFile")
            return dict(rejected=len(bad), native_open_calls=0)

        run("lexical_namespace_rejections", grammar)
        run("wrong_types_and_missing", lambda: dict(statuses=[
            denied(lambda: api.at(held, "direct.bin", True), {NOT_DIR}),
            denied(lambda: api.read(held, "nested"), {IS_DIR}),
            denied(lambda: api.read(held, "missing.bin"), {MISSING})]))

        def junctions():
            api.junction(root / "junction", outside)
            return dict(statuses=[
                denied(lambda: api.at(held, "junction", True), {RPE}),
                denied(lambda: api.read(held, "junction/bytes.bin"), {RPE})])

        run("junction_leaf_and_intermediate", junctions)

        def root_alias():
            alias = base / "owner-root"
            api.junction(alias, root)
            try:
                with api.trusted_root(alias) as selected:
                    check(api.identity(selected) == api.identity(held), "bootstrap selected wrong root")
                    alias.rmdir()
                    api.junction(alias, outside)
                    check(api.read(selected, "direct.bin") == GOOD, "root retarget affected handle")
                    status = denied(lambda: api.read(selected, "escape.bin"), {MISSING})
                    return dict(owner_selected_junction=True, retarget_status=status)
            finally:
                alias.rmdir()

        run("trusted_root_junction_and_retarget", root_alias)

        def symlinks():
            api.symlink(root / "link.bin", outside / "bytes.bin")
            api.symlink(root / "linkdir", outside, directory=True)
            return dict(statuses=[
                denied(lambda: api.read(held, "link.bin"), {RPE}),
                denied(lambda: api.read(held, "linkdir/bytes.bin"), {RPE})])

        run("file_and_directory_symlinks", symlinks)

        def swap_after_listing():
            directory = root / "listed"
            directory.mkdir()
            (directory / "bytes.bin").write_bytes(GOOD)
            check("listed" in api.names(held), "listing did not include victim")
            directory.rename(root / "listed-original")
            api.junction(directory, outside)
            return dict(status=denied(lambda: api.read(held, "listed/bytes.bin"), {RPE}))

        run("race_directory_swap_after_listing", swap_after_listing)

        def rename_parent():
            directory = root / "parent"
            directory.mkdir()
            (directory / "bytes.bin").write_bytes(GOOD)
            with api.at(held, "parent", True) as parent:
                identity = api.identity(parent)
                directory.rename(root / "parent-original")
                api.junction(directory, outside)
                check(api.identity(parent) == identity, "held directory changed identity")
                check(api.read(parent, "bytes.bin") == GOOD, "ancestor replacement redirected read")
                status = denied(lambda: api.read(parent, "escape.bin"), {MISSING})
                return dict(held_identity=identity, outside_status=status)

        run("race_parent_rename_and_junction_replacement", rename_parent)

        def mutate_held_directory():
            directory = root / "mutating"
            directory.mkdir()
            with api.at(held, "mutating", True) as parent:
                # A rename lock alone cannot address this race: mutate the same
                # empty directory into a junction AFTER its type was checked.
                api.junction(directory, outside, existing=True)
                status = denied(lambda: api.read(parent, "escape.bin"), {RPE, MISSING})
                return dict(status=status, mutation_completed=True)

        run("race_held_directory_becomes_reparse", mutate_held_directory)

        def leaf_after_listing():
            victim = root / "listed-leaf.bin"
            victim.write_bytes(GOOD)
            check(victim.name in api.names(held), "missing listed leaf")
            victim.unlink()
            api.symlink(victim, outside / "bytes.bin")
            return dict(status=denied(lambda: api.read(held, victim.name), {RPE}))

        run("race_leaf_swap_after_listing", leaf_after_listing)

        def held_file():
            victim = root / "held.bin"
            victim.write_bytes(GOOD)
            with api.at(held, victim.name, False) as opened:
                identity = api.identity(opened)
                victim.rename(root / "held-original.bin")
                victim.write_bytes(BAD)
                check(api.read_handle(opened) == GOOD, "open file switched to replacement bytes")
                return dict(held_identity=identity, bytes=len(GOOD))

        run("race_file_replacement_after_open", held_file)

        def pipe_case():
            name = "\\\\.\\pipe\\probe1297-" + uuid.uuid4().hex
            # Duplex, FIRST_PIPE_INSTANCE; byte mode, NOWAIT, REJECT_REMOTE_CLIENTS.
            with api.owned(api.pipe_create(name, 0x80003, 0x9, 1, 4096, 4096, 0, None)) as pipe:
                api.pipe_connect(pipe.value, None)  # put NOWAIT pipe into listening state
                with api.owned(api.create(name, 0x80000000, 0, None, 3, 0, None)):
                    ok = api.pipe_connect(pipe.value, None)
                    check(ok or C.get_last_error() == 535, "pipe observer failed calibration")
                check(api.pipe_disconnect(pipe.value), "pipe disconnect failed")
                api.pipe_connect(pipe.value, None)
                api.symlink(root / "pipe-link", name)
                status = denied(lambda: api.read(held, "pipe-link"), {RPE})
                ok = api.pipe_connect(pipe.value, None)
                error = C.get_last_error()
                check(not ok and error == 536, f"pipe contact or invalid observer: {ok}, {error}")
                return dict(status=status, calibrated=True, pipe_contacts=0)

        run("named_pipe_reparse_no_contact", pipe_case)

        def unc_case():
            with LoopbackObserver() as observer:
                target = "\\\\127.0.0.1\\probe1297-" + uuid.uuid4().hex
                api.symlink(root / "unc", target, directory=True)
                started = time.time_ns()
                try:
                    status = denied(lambda: api.read(held, "unc/bytes.bin"), {RPE})
                finally:
                    observation = observer.observe(2.0)
                    emit("observation", case="unc_reparse_no_tcp_contact", observed=observation)
                ended = time.time_ns()
                check(not observation["syn_ports"] and observation["connections"] == 0,
                      f"UNC contact observed: {observation}")
                # Calibrate the actual filesystem-to-SMB path AFTER the negative
                # window. An installed-but-disabled redirector is not a pass.
                # Our sinks never negotiate SMB, so no authentication challenge
                # can be sent. Terminate only this owned control child if needed.
                command = [sys.executable, "-B", os.path.abspath(__file__),
                           "--unc-control", target + "\\bytes.bin"]
                control_env = dict(os.environ, PROBE1297_UNC_CONTROL=target + "\\bytes.bin")
                with subprocess.Popen(command, env=control_env) as control:
                    try:
                        redirector = observer.observe(3.0)
                    finally:
                        if control.poll() is None:
                            control.kill()
                        control.wait()
                emit("unc_calibration", phase="filesystem_unc", observed=redirector,
                     control_returncode=control.returncode)
                if 445 not in redirector["syn_ports"] or redirector["connections"] < 1:
                    raise Skip(f"real UNC control did not calibrate: {redirector}; negative={observation}")
                return dict(status=status, target=target, started_ns=started,
                            ended_ns=ended, calibration=observer.calibration,
                            redirector_calibration=redirector,
                            observed=observation, oracle="calibrated IPv4 loopback TCP SYN + accept")

        run("unc_reparse_no_tcp_contact", unc_case)
        check((outside / "bytes.bin").read_bytes() == BAD, "outside fixture was modified")


def worker(args):
    results = []

    def run(name, fn):
        emit("case_start", case=name)
        try:
            detail, status = fn() or {}, "PASS"
        except Skip as exc:
            detail, status = dict(reason=str(exc)), "SKIP"
        except Exception as exc:
            detail, status = dict(error=f"{type(exc).__name__}: {exc}"), "FAIL"
        results.append(status)
        emit("case", case=name, status=status, detail=detail)
        return status == "PASS"

    api = None
    try:
        api = Win()
        work = os.path.abspath(args.work_dir)
        check(len(work) >= 3 and work[1:3] == ":\\", "work-dir must be host-trusted local drive path")
        # Everything, including temporary fixtures, is beneath the chosen work directory.
        with tempfile.TemporaryDirectory(prefix="probe1297-", dir=work) as temporary:
            emit("start", platform=platform.platform(), python=sys.version, pid=os.getpid(),
                 fixture_root=temporary, source_revision="fef394094", native=True)
            cases(api, Path(temporary), run)
        check(not api.live, "native handle ownership leak")
        emit("cleanup", status="PASS", fixture_removed=True, native_handles=len(api.live))
    except Skip as exc:
        results.append("SKIP")
        emit("case", case="prerequisites", status="SKIP", reason=str(exc))
    except Exception as exc:
        results.append("FAIL")
        emit("case", case="setup_or_cleanup", status="FAIL", error=f"{type(exc).__name__}: {exc}")
    counts = {status: results.count(status) for status in ("PASS", "FAIL", "SKIP")}
    overall = "FAIL" if counts["FAIL"] else "INCOMPLETE" if counts["SKIP"] else "PASS"
    emit("summary", status=overall, counts=counts, native=True)
    return {"PASS": 0, "FAIL": 1, "INCOMPLETE": 3}[overall]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default=".", help="host-trusted local NTFS scratch directory")
    parser.add_argument("--timeout", type=float, default=90, help="native child deadline in seconds")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--unc-control", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sys.platform != "win32":
        emit("summary", status="NOT_RUN", native=False, platform=sys.platform,
             reason="requires native Windows; no emulation or fallback")
        return 2
    if sys.version_info < (3, 11) or platform.machine().upper() not in ("AMD64", "X86_64"):
        emit("summary", status="NOT_RUN", native=False, reason="requires Python 3.11+ on Windows x64")
        return 2
    if args.unc_control:
        import re
        import threading
        # No arbitrary server or path is accepted by the internal control mode.
        if (os.environ.get("PROBE1297_UNC_CONTROL") != args.unc_control or
                not re.fullmatch(r"\\\\127\.0\.0\.1\\probe1297-[0-9a-f]{32}\\bytes\.bin", args.unc_control)):
            return 1
        # Bounds this control process even if its parent is interrupted. It owns
        # no filesystem fixtures; process exit releases its native handles.
        deadline = threading.Timer(6.0, lambda: os._exit(124))
        deadline.daemon = True
        deadline.start()
        api = Win()
        try:
            with api.owned(api.create(args.unc_control, 0x80000000, 7, None, 3, 0, None)):
                pass
        except OSError:
            pass  # Sinks close TCP without speaking SMB. Only contact is measured.
        finally:
            deadline.cancel()
        return 0
    if args.worker:
        return worker(args)
    # Only the actual child object is terminated on timeout, never a guessed PID.
    # Native synchronous calls may hang if the hypothesis fails; retain prior JSON.
    command = [sys.executable, "-B", os.path.abspath(__file__), "--worker", "--work-dir", args.work_dir]
    with subprocess.Popen(command) as child:
        try:
            code = child.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
            emit("summary", status="FAIL", reason="native_timeout", child_pid=child.pid,
                 native=True, fixture_cleanup="not guaranteed; inspect logged fixture_root")
            return 1
    if code not in (0, 1, 2, 3):
        emit("summary", status="FAIL", reason="native_child_abnormal_exit", returncode=code, native=True)
        return 1
    return code


if __name__ == "__main__":
    sys.exit(main())
