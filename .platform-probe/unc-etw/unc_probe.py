#!/usr/bin/env python3
"""#1297 observer experiment; no product imports. Read README.md before native use.

Exit 0: bounded calibrated PASS; 1: candidate FAIL; 2: native NOT_RUN;
3: INCOMPLETE (observer/setup/control/cleanup could not establish the oracle).
"""
import argparse
import contextlib
import ctypes as C
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import queue
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time

CANDIDATE_SHA256 = "3121e4f39bf84626d687a1407d015e26f17c137159e1a39155b812b4a9c9ae8e"
ATTEMPT_OPS = {10, 12, 14, 16}  # Send, Connect, Retransmit, Reconnect; see sources.
WINDOW = 12


class Incomplete(Exception):
    pass


def emit(event, **fields):
    print(json.dumps(dict(event=event, **fields), sort_keys=True), flush=True)


def load_candidate(path):
    path = Path(path).resolve()
    if hashlib.sha256(path.read_bytes()).hexdigest() != CANDIDATE_SHA256:
        raise Incomplete("candidate digest differs from the inspected original; no silent substitution")
    spec = importlib.util.spec_from_file_location("candidate1297", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def local_path(text):
    path = Path(text).resolve()
    if len(str(path)) < 3 or str(path)[1:3] != ":\\":
        raise Incomplete("requires a trusted local-drive path")
    return path


def fresh_target(used):
    while True:
        address = f"127.{secrets.randbelow(254) + 1}.{secrets.randbelow(256)}.{secrets.randbelow(254) + 1}"
        if address not in used:
            used.add(address)
            return address


def count(observation, ports, attempts=False):
    return sum(r["count"] for r in observation["records"]
               if r["port"] in ports and (not attempts or r["opcode"] in ATTEMPT_OPS))


def require_observer(observation, heartbeat_ports):
    # Treat missing/malformed fields as an error, never default absent evidence to 0.
    fields = ("unsupported", "events_lost", "log_buffers_lost", "realtime_buffers_lost",
              "stop_code", "process_code", "close_code")
    if observation["complete"] is not True or any(observation[f] != 0 for f in fields):
        raise Incomplete("ETW decoding, loss, stop, or drain did not complete cleanly")
    if any(count(observation, {p}, attempts=True) < 1 for p in heartbeat_ports):
        raise Incomplete("a TCP heartbeat in this exact window was invisible")


def bound_socket(target, listening):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind((target, 0))  # ephemeral control ports ONLY; never 445/139
        sock.settimeout(1)
        if listening:
            sock.listen(1)
        return sock
    except BaseException:
        sock.close()
        raise


def heartbeat(listener):
    with socket.create_connection(listener.getsockname(), timeout=1) as client:
        with listener.accept()[0] as accepted:
            accepted.settimeout(1)
            client.sendall(b"1297")
            if accepted.recv(4) != b"1297":
                raise Incomplete("synthetic TCP heartbeat failed")


def window(args, phase, target, operation, test_port=0):
    """Retain the entire helper transcript: it contains only scoped numeric metadata."""
    emit("window_start", phase=phase, target=target, seconds=WINDOW)
    with contextlib.ExitStack() as stack:
        pre = stack.enter_context(bound_socket(target, True))
        post = stack.enter_context(bound_socket(target, True))
        ports = [pre.getsockname()[1], post.getsockname()[1]]
        command = [str(args.observer), target, *map(str, ports), str(test_port), str(WINDOW)]
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8") as observer:
            lines, first = [], queue.Queue()

            def collect():
                for line in observer.stdout:
                    lines.append(line)
                    if len(lines) == 1:
                        first.put(line)
                if not lines:
                    first.put("")

            reader = threading.Thread(target=collect, daemon=True)
            reader.start()
            failure = None
            result = None
            try:
                ready = json.loads(first.get(timeout=5))
                if ready.get("event") != "ready":
                    raise Incomplete("observer did not start a new owned session")
                started = time.monotonic()
                heartbeat(pre)
                result = operation()
                heartbeat(post)
                if time.monotonic() - started > WINDOW - 3:
                    raise Incomplete("operation left less than 3 seconds of observation tail")
            except Exception as exc:
                failure = exc
            finally:
                # Allow its independent timer and STOP/drain to finish even on child failure.
                try:
                    observer.wait(timeout=WINDOW + 12)
                except subprocess.TimeoutExpired:
                    observer.kill()  # only the Popen-owned process
                    observer.wait()
                    failure = Incomplete("observer deadline exceeded; ETW cleanup unconfirmed; discard runner")
                reader.join(timeout=2)
                if reader.is_alive():
                    failure = Incomplete("observer output reader did not finish; transcript incomplete")
                log = args.output / f"{phase}-observer.jsonl"
                log.write_text("".join(lines), encoding="utf-8")
            records = [json.loads(line) for line in lines]
            observations = [r for r in records if r.get("event") == "observation"]
            if len(observations) == 1:
                emit("window", phase=phase, target=target, heartbeat_ports=ports,
                     observation=observations[0], operation=result)
            if failure:
                raise failure
            if observer.returncode != 0 or len(observations) != 1:
                raise Incomplete(f"{phase}: observer unavailable; inspect {log.name}")
            observation = observations[0]
            require_observer(observation, ports)
            return observation, result


@contextlib.contextmanager
def runner_identity():
    """Fresh hosted-runner identity against its own loopback SMB only.

    Anonymous UNC returned Win64 without an observable TCP attempt in r3. This
    separate experiment uses the runner's normal identity for BOTH paths; any OS
    authentication stays on this disposable machine. No owner identity or supplied
    credential is used, and no authentication payload is recorded.
    """
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Windows":
        raise Incomplete("default-token control requires the disposable hosted Windows job")
    yield


def unsafe_at(api, held):
    # Deliberate control mutation: omit OBJ_DONT_REPARSE. Original api.at/read
    # are untouched. The trusted local root handle belongs to this runner fixture.
    text = C.create_unicode_buffer("unc\\bytes.bin")
    length = len(text.value.encode("utf-16-le"))
    name = api.Unicode(length, length + 2, C.cast(text, C.c_void_p))
    attrs = api.Attrs(C.sizeof(api.Attrs), held.value, C.pointer(name), 0x40, None, None)
    out, iosb = C.c_void_p(), api.IOSB()
    status = api.ntcreate(C.byref(out), 0x100081, C.byref(attrs), C.byref(iosb),
                          None, 0, 7, 1, 0x60, None, 0)
    if status >= 0 and out.value not in (None, C.c_void_p(-1).value):
        api.owned(out.value).close()
    return {"ntstatus": f"0x{status & 0xFFFFFFFF:08X}", "attributes": "0x40"}


def child(args):
    if os.environ.get("PROBE1297_CHILD") != args.child:
        return 3
    timer = threading.Timer(6, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    module = load_candidate(args.candidate)
    api = module.Win()
    try:
        if args.child == "direct":
            address = ipaddress.ip_address(args.target)
            if (address.version != 4 or not address.is_loopback or
                    not re.fullmatch(r"probe1297-[0-9a-f]{32}", args.share)):
                raise Incomplete("invalid internal target")
            with runner_identity():
                emit("operation_begin", kind="direct", identity="ephemeral_windows_runner")
                try:
                    with api.owned(api.create(f"\\\\{address}\\{args.share}\\bytes.bin",
                                              0x80000000, 7, None, 3, 0, None)):
                        detail = {"opened": True}
                except OSError as exc:
                    detail = {"winerror": exc.winerror, "opened": False}
        else:
            with api.trusted_root(local_path(args.root)) as held:
                if args.child == "safe":
                    if api.read(held, "local.bin") != module.GOOD:
                        raise AssertionError("candidate local positive failed")
                    with runner_identity():
                        emit("operation_begin", kind="safe", identity="ephemeral_windows_runner")
                        detail = {"ntstatus": module.denied(
                            lambda: api.read(held, "unc/bytes.bin"), {module.RPE}),
                            "attributes": "0x1040", "local_positive": True}
                else:
                    with runner_identity():
                        emit("operation_begin", kind="unsafe", identity="ephemeral_windows_runner")
                        detail = unsafe_at(api, held)
        if api.live:
            raise AssertionError("native handle leak")
        emit("operation_end", kind=args.child, **detail)
        return 0
    finally:
        timer.cancel()


def operation(args, kind, **fields):
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--candidate",
               str(args.candidate), "--child", kind]
    for key, value in fields.items():
        command.extend(["--" + key, str(value)])
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8",
                          env=dict(os.environ, PROBE1297_CHILD=kind)) as process:
        timed_out = False
        try:
            stdout, _ = process.communicate(timeout=4)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            stdout, _ = process.communicate(timeout=2)
    # Only our fixed-path child's output; never execute shell or print environment.
    (args.output / f"{args.phase}-operation.jsonl").write_text(stdout, encoding="utf-8")
    rows = [json.loads(line) for line in stdout.splitlines()]
    if not any(r.get("event") == "operation_begin" and r.get("kind") == kind for r in rows):
        raise Incomplete(f"{kind}: child did not enter the filesystem operation")
    if kind == "safe" and (timed_out or process.returncode != 0):
        raise AssertionError("candidate failed or timed out; inspect safe-operation.jsonl")
    if not timed_out and process.returncode != 0:
        raise Incomplete(f"{kind}: child failed before a usable control result")
    return dict(kind=kind, timed_out=timed_out, returncode=process.returncode, records=rows)


def run(args):
    module = load_candidate(args.candidate)
    api = module.Win()
    used = set()

    # Calibrate attempted connections independently of peer acceptance. Native
    # r1/r2 recorded reconnect events while Winsock still returned WSAEWOULDBLOCK;
    # that is an incomplete connection, not a refused or successful connection.
    # Every target port must nevertheless produce its own attempt event. Real
    # filesystem-to-UNC and same-symlink unsafe controls remain separately required.
    tcp_target = fresh_target(used)
    with bound_socket(tcp_target, False) as guard:
        port = guard.getsockname()[1]
        # Release the selected port. Native observations showed an unfinished
        # connection both before and after this change; its cause is unknown.
        # A concurrent listener that accepts this connection invalidates the fixture.
        guard.close()

        def attempt_controls():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                code = sock.connect_ex((tcp_target, port))
            if code not in (10061, 10035, 10060):
                raise Incomplete(f"unexpected unaccepted-connect control result: {code}")
            results = {str(port): code}
            # No SMB request or credentials: plain TCP to the existing local ports.
            # Preserve both 445 and 139 calibration without owning either port.
            for smb_port in (445, 139):
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    results[str(smb_port)] = sock.connect_ex((tcp_target, smb_port))
                if results[str(smb_port)] not in (0, 10061, 10035, 10060):
                    raise Incomplete(f"unexpected TCP {smb_port} control outcome")
            return {"connect_results": results, "unaccepted_port": port,
                    "completion": "raw Winsock results; timeout is not refusal"}

        obs, _ = window(args, "tcp_attempts", tcp_target, attempt_controls, port)
        for required in (port, 445, 139):
            if count(obs, {required}, attempts=True) == 0:
                raise Incomplete(f"TcpIp ETW did not expose control port {required}; attempt/SMB oracle unavailable")

    for phase in ("direct_before", "direct_after"):
        # Put safe + unsafe between the two independent UNC calibrations.
        if phase == "direct_after":
            target = fresh_target(used)
            share = "probe1297-" + secrets.token_hex(16)
            with tempfile.TemporaryDirectory(prefix="unc1297-", dir=args.work_dir) as temporary:
                root = Path(temporary)
                (root / "local.bin").write_bytes(module.GOOD)
                with api.trusted_root(root) as held:
                    fs = C.create_unicode_buffer(64)
                    if not api.volume(held.value, None, 0, None, None, None, fs, len(fs)):
                        raise C.WinError(C.get_last_error())
                    if fs.value != "NTFS":
                        raise Incomplete("fixture is not on NTFS")
                api.symlink(root / "unc", f"\\\\{target}\\{share}", directory=True)
                try:
                    args.phase = "safe"
                    obs, _ = window(args, "safe", target,
                                    lambda: operation(args, "safe", root=root))
                    if count(obs, {445, 139}):
                        raise AssertionError("safe handle-relative traversal generated scoped SMB TCP events")
                    args.phase = "unsafe"
                    obs, _ = window(args, "unsafe", target,
                                    lambda: operation(args, "unsafe", root=root))
                    if not count(obs, {445}, attempts=True):
                        raise Incomplete("unsafe traversal did not calibrate port 445; negative is unproven")
                finally:
                    # Remove reparse point itself; never recursively follow its UNC target.
                    (root / "unc").rmdir()
        target = fresh_target(used)
        share = "probe1297-" + secrets.token_hex(16)
        args.phase = phase
        obs, _ = window(args, phase, target,
                        lambda: operation(args, "direct", target=target, share=share))
        if not count(obs, {445}, attempts=True):
            raise Incomplete(f"{phase}: real runner-identity filesystem-to-UNC did not calibrate port 445")
    if api.live:
        raise Incomplete("fixture native handles leaked")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--observer", type=Path, default=Path("tcp_observer.exe"))
    parser.add_argument("--work-dir", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("evidence"))
    parser.add_argument("--child", choices=("direct", "safe", "unsafe"), help=argparse.SUPPRESS)
    for name in ("target", "share", "root"):
        parser.add_argument("--" + name, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sys.platform != "win32":
        emit("summary", status="NOT_RUN", native=False, reason="native Windows x64 required")
        return 2
    if C.sizeof(C.c_void_p) != 8 or sys.version_info < (3, 11):
        emit("summary", status="NOT_RUN", native=False, reason="Python 3.11+ x64 required")
        return 2
    if args.child:
        try:
            return child(args)
        except Exception as exc:
            emit("operation_error", kind=args.child, error_type=type(exc).__name__, error=str(exc))
            return 1
    status, reason = "PASS", "calibrated bounded IPv4 loopback TCP observation"
    try:
        args.candidate = local_path(args.candidate)
        args.observer = local_path(args.observer)
        args.work_dir = local_path(args.work_dir)
        args.output = local_path(args.output)
        args.output.mkdir(parents=True, exist_ok=False)  # never overwrite a prior run
        emit("start", native=True, candidate_sha256=CANDIDATE_SHA256,
             observer_sha256=hashlib.sha256(args.observer.read_bytes()).hexdigest(),
             windows_build=sys.getwindowsversion().build, window_seconds=WINDOW)
        run(args)
    except AssertionError as exc:
        status, reason = "FAIL", str(exc)
    except Exception as exc:
        status, reason = "INCOMPLETE", f"{type(exc).__name__}: {exc}"
    emit("summary", native=True, status=status, reason=reason)
    return {"PASS": 0, "FAIL": 1, "INCOMPLETE": 3}[status]


if __name__ == "__main__":
    sys.exit(main())
