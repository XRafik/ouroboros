# #1297: bounded UNC observer experiment

**Native status: NOT_RUN.** This is an executable feasibility candidate for the
parent's disposable GitHub Windows2022 job. No Windows observation or thirteenth
case PASS is claimed. The existing twelve-case result remains separate.

The observer uses an owned ETW system-logger session and the documented TcpIp
metadata provider. It never binds 445/139, stops services, changes firewall or
registry state, installs drivers, creates SMB shares, or supplies credentials.
PID 4 may continue to own SMB. This removes the demonstrated port-ownership
bottleneck; it does **not** establish that this ETW provider observes every SYN.
The first native control tests that unresolved premise and stops INCOMPLETE if
it cannot observe a refused connection attempt.

Files are research deliverables, not product changes. `unc_probe.py` imports
`Win`, `read`, `denied`, and fixture helpers from the existing experiment, whose
entire source SHA-256 must be
`3121e4f39bf84626d687a1407d015e26f17c137159e1a39155b812b4a9c9ae8e`.
The safe call remains `api.read(held, "unc/bytes.bin")`, with the original
component grammar, RootDirectory handling, access/options, and `0x1040` attributes.
The separate unsafe control intentionally opens `unc\bytes.bin` relative to a
held root with `0x40`, allowing reparsing. It is never a candidate fallback.
Both paths run in the same anonymous thread context after acquiring their
trusted local root handles. The local positive read runs before impersonation.
This avoids credential use even if the safe path leaks. Anonymous access denial
cannot stand in for the required RPE status, and the anonymous unsafe path must
still make observable contact. This token context is an explicit difference
from the earlier runner-identity experiment; its original cases are untouched.

Run once on a **fresh** runner; do not reuse the runner with `srvnet` STOP_PENDING.
After the parent places these files at `.platform-probe/unc-etw/`, add this step
to the existing manual, secretless `windows-2022` job. Keep a six-minute job
timeout and do not build the product:

```yaml
- name: UNC ETW feasibility
  shell: pwsh
  timeout-minutes: 5
  run: |
    & ./.platform-probe/unc-etw/run_windows.ps1 `
      -Candidate ./.platform-probe/windows_relative_probe.py `
      -RunDirectory "$env:RUNNER_TEMP/unc1297-etw-r1"
    exit $LASTEXITCODE
```

The recipe uses the runner's installed MSVC x64/Windows SDK and Python 3.11+ x64;
no downloads or packages are required. It rejects a non-`win22` GitHub runner,
requires a new output directory, preserves compiler output and every owned child
transcript, and bounds the orchestrator to 180 seconds. Each ETW helper stops its
own session after 12 seconds and allows eight seconds for draining; each
filesystem child has an independent six-second watchdog and is normally killed
by its parent after four seconds if still blocked. A session-name collision is
INCOMPLETE; no existing session is adopted or stopped. After an abnormal cleanup,
discard the disposable runner; do not repeat service/driver stop commands.

Retain only the new run directory's `build.log`, `run.jsonl`, `run.stderr.log`, and
`evidence/*.jsonl` as artifacts, including on failure. Do not upload system logs,
ETL files, packet captures, scratch fixtures, or the runner environment. The
runner recipe does not publish or dispatch anything.

The sequence is:

1. On a fresh numeric `127.x.y.z`, select an ephemeral port and release its
   socket before connecting (the first native bound/nonlistener control returned
   WSAEWOULDBLOCK, not a proven refusal). Require `WSAECONNREFUSED` and an attributable ETW Send, Connect,
   Retransmit, or Reconnect event for that port. Also require visible plain TCP
   controls to both 445 and 139. A Disconnect event alone cannot calibrate an
   attempt. Successful heartbeat traffic cannot satisfy the refused-port gate.
2. On another fresh address/share, attempt a real `CreateFileW` UNC open under
   `ImpersonateAnonymousToken`. Require a port-445 attempt event; the file need
   not open. Anonymous rejection before networking is INCOMPLETE.
3. Create a verified directory symlink to a third, unused address/share. In a
   fresh observer window, prove a local read works, switch to anonymous context,
   then require the original safe path's `STATUS_REPARSE_POINT_ENCOUNTERED` and
   zero scoped 445/139 events.
4. In a separate window, traverse **that same symlink** with the deliberately
   unsafe native call, anonymously. Require a port-445 attempt event. This
   independently tests the mutation and the actual filesystem-to-UNC route.
5. Repeat the direct UNC calibration on another fresh address/share.

Every window has separate ephemeral TCP heartbeat ports before and after the
operation. All PIDs are included, so SMB redirector work attributed to SYSTEM is
not lost to a child-PID filter. The safe target is never touched by SMB controls
before the safe window. Fresh numeric addresses avoid DNS and reduce server/session
and failure-cache reuse; unique share names alone would not achieve that. Any
alias canonicalization, local fast path, or caching that makes an unsafe control
invisible blocks PASS. No caches are flushed. No owner credentials are used;
anonymous control failure has no authenticated retry.

Exit codes are 0 PASS, 1 FAIL, 2 NOT_RUN, 3 INCOMPLETE. A safe native refusal alone
cannot pass. Unknown versions/layouts, unattributable TcpIp Fail events, ETW loss,
missing heartbeats, control failure, or stop/drain failure invalidate absence.
The helper retains counts by target port, event opcode, and payload PID. It does
not retain addresses other than the generated target or any packet bytes.

This classic ETW source emits machine-wide **network metadata into memory** during
the bounded window; destination filtering happens immediately in the consumer,
not in the kernel. Unrelated records are discarded, never serialized or printed.
No ETL is written. `NO_SYSCONFIG` disables system-configuration rundown. This is
not a claim of kernel-side IP filtering. If acquisition of even unrelated network
metadata in transient ETW buffers is unacceptable, this backend is unsuitable.

A native PASS would mean: the original safe operation returned the required
native refusal and produced no target TCP metadata during this bounded window,
while this runner demonstrated observer liveness, refused-attempt visibility,
and direct/unsafe UNC contact without reported ETW loss. It would **not** prove
packet-for-packet SYN capture, every network protocol, IPv6, external hosts, a
successful remote read, arbitrary delayed work after the window, or universal
confinement. Keep this narrower evidence distinct from the old SYN-plus-accept
oracle; do not silently replace that oracle or label the original case passed.

If the refused control is invisible, the precise blocker is that documented
classic TcpIp metadata has not provided an attributable initial failed attempt
on this runner. Next investigate the runner's TCPIP provider manifest for a
documented, target-filterable connect-attempt event, or an already-enabled WFP
subscription with address/port conditions and observable loss behavior. Those
are follow-up experiments, not implemented fallbacks. Pktmon's documented
counters-only mode avoids payload logging, but Microsoft documentation inspected
here did not establish loopback coverage. WFP event configuration can be
system-wide and persistent, so this probe does not enable it or change policy.

Sources checked on 2026-10-21:

- [StartTraceW](https://learn.microsoft.com/en-us/windows/win32/api/evntrace/nf-evntrace-starttracew):
  system-logger mode, session ownership, administrative access and resource limits.
  This probe uses a descriptive fixed name and never uses `NT Kernel Logger`.
- [EVENT_TRACE_PROPERTIES](https://learn.microsoft.com/en-us/windows/win32/api/evntrace/ns-evntrace-event_trace_properties):
  network enable flag, `NO_SYSCONFIG`, buffers and loss counters.
- [TcpIp](https://learn.microsoft.com/en-us/windows/win32/etw/tcpip),
  [TypeGroup1](https://learn.microsoft.com/en-us/windows/win32/etw/tcpip-typegroup1),
  [TypeGroup2](https://learn.microsoft.com/en-us/windows/win32/etw/tcpip-typegroup2),
  [SendIPV4](https://learn.microsoft.com/en-us/windows/win32/etw/tcpip-sendipv4):
  provider GUID, opcodes, v2 IPv4 prefix and payload PID. Header PID need not be
  the network originator. These pages do not promise one event per initial SYN.
- [ControlTraceW](https://learn.microsoft.com/en-us/windows/win32/api/evntrace/nf-evntrace-controltracew)
  and [ProcessTrace](https://learn.microsoft.com/en-us/windows/win32/api/evntrace/nf-evntrace-processtrace):
  stop/flush and consumer draining. Both must complete before assessing absence.
- [ImpersonateAnonymousToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-impersonateanonymoustoken):
  anonymous network access without account credentials.
- [NtCreateFile](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile):
  RootDirectory-relative names used by the deliberate unsafe control.
- [Pktmon start](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/pktmon-start),
  [WFP event conditions](https://learn.microsoft.com/en-us/windows/win32/api/fwpmtypes/ns-fwpmtypes-fwpm_net_event_enum_template0),
  [WFP engine options](https://learn.microsoft.com/en-us/windows/win32/api/fwpmu/nf-fwpmu-fwpmenginesetoption0):
  alternatives and their limits; no claim that they were exercised here.

Portable validation is in `checks/portable.json`. It exercises scope/byte-order
decoding (including SYSTEM), lost/unknown evidence, control isolation, and the
non-Windows NOT_RUN path. It does not compile Windows SDK code or prove native
behavior. No independent review or acceptance has been performed by this worker.
