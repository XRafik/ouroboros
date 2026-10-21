// Research only: one bounded ETW system logger, no ETL or packet capture.
// Build: cl /nologo /EHsc /W4 /std:c++17 tcp_observer.cpp /link advapi32.lib
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <evntrace.h>
#include <evntcons.h>
#include <array>
#include <atomic>
#include <cstdio>
#include <cwchar>
#include <map>
#include <tuple>
#include "tcp_scope.hpp"

static constexpr wchar_t session_name[] = L"Probe1297-UNC-TCP";
static constexpr GUID tcp_guid =
    {0x9a280ac0, 0xc8e0, 0x11d1, {0x84,0xe2,0x00,0xc0,0x4f,0xb9,0x98,0xa2}};
static std::array<unsigned char, 4> target{};
static std::array<std::uint16_t, 3> control_ports{};
static unsigned long long matched = 0, attempts = 0, unsupported = 0;
static std::map<std::tuple<unsigned, unsigned, unsigned>, unsigned long long> counts;
static TRACEHANDLE consumer = INVALID_PROCESSTRACE_HANDLE;
static std::atomic<ULONG> process_code{ERROR_IO_PENDING};

static void WINAPI event_record(PEVENT_RECORD event) {
    if (!IsEqualGUID(event->EventHeader.ProviderId, tcp_guid)) return;
    probe1297::Record record;
    const auto result = probe1297::decode(event->EventHeader.EventDescriptor.Version,
        event->EventHeader.EventDescriptor.Opcode, event->UserData, event->UserDataLength,
        target, control_ports, record);
    if (result == probe1297::Decode::unsupported) { ++unsupported; return; }
    if (result != probe1297::Decode::match) return;
    ++matched;
    if (probe1297::attempt(record.opcode)) ++attempts;
    // Bound retained memory. Overflow invalidates the observation.
    const auto key = std::make_tuple(record.pid, record.port, record.opcode);
    auto existing = counts.find(key);
    if (existing != counts.end()) ++existing->second;
    else if (counts.size() < 128) counts.emplace(key, 1);
    else ++unsupported;
}

static DWORD WINAPI consume(void*) {
    process_code = ProcessTrace(&consumer, 1, nullptr, nullptr);
    return 0;
}

struct Properties {
    EVENT_TRACE_PROPERTIES p{};
    wchar_t name[128]{};
    Properties() {
        p.Wnode.BufferSize = sizeof(*this);
        p.Wnode.Flags = WNODE_FLAG_TRACED_GUID;
        p.Wnode.ClientContext = 1; // QPC
        p.BufferSize = 64;         // KB, only metadata
        p.MinimumBuffers = 16;
        p.MaximumBuffers = 64;
        p.FlushTimer = 1;
        p.LogFileMode = EVENT_TRACE_REAL_TIME_MODE | EVENT_TRACE_SYSTEM_LOGGER_MODE;
        p.EnableFlags = EVENT_TRACE_FLAG_NETWORK_TCPIP | EVENT_TRACE_FLAG_NO_SYSCONFIG;
        p.LoggerNameOffset = offsetof(Properties, name);
    }
};

static int error(const char* stage, ULONG code) {
    std::printf("{\"event\":\"observer_error\",\"stage\":\"%s\",\"code\":%lu}\n", stage, code);
    std::fflush(stdout);
    return 3;
}

int wmain(int argc, wchar_t** argv) {
    unsigned a, b, c, d, port1, port2, port3, seconds;
    wchar_t tail;
    if (argc != 6 || std::swscanf(argv[1], L"%u.%u.%u.%u%c", &a,&b,&c,&d,&tail) != 4 ||
        a != 127 || b == 0 || b > 254 || c > 255 || d == 0 || d > 254 ||
        std::swscanf(argv[2], L"%u%c", &port1,&tail) != 1 || port1 < 1024 || port1 > 65535 ||
        std::swscanf(argv[3], L"%u%c", &port2,&tail) != 1 || port2 < 1024 || port2 > 65535 ||
        std::swscanf(argv[4], L"%u%c", &port3,&tail) != 1 || port3 > 65535 ||
        (port3 && port3 < 1024) ||
        std::swscanf(argv[5], L"%u%c", &seconds,&tail) != 1 || seconds < 3 || seconds > 15)
        return error("arguments", ERROR_INVALID_PARAMETER);
    target = {127, static_cast<unsigned char>(b), static_cast<unsigned char>(c),
              static_cast<unsigned char>(d)};
    control_ports = {static_cast<std::uint16_t>(port1), static_cast<std::uint16_t>(port2),
                     static_cast<std::uint16_t>(port3)};
    Properties properties;
    TRACEHANDLE session = 0;
    ULONG code = StartTraceW(&session, session_name, &properties.p);
    if (code) return error("StartTraceW", code); // NEVER stop an existing session.

    EVENT_TRACE_LOGFILEW log{};
    log.LoggerName = const_cast<wchar_t*>(session_name);
    log.ProcessTraceMode = PROCESS_TRACE_MODE_REAL_TIME | PROCESS_TRACE_MODE_EVENT_RECORD;
    log.EventRecordCallback = event_record;
    consumer = OpenTraceW(&log);
    if (consumer == INVALID_PROCESSTRACE_HANDLE) {
        const auto saved = GetLastError();
        Properties stop;
        const auto stopped = ControlTraceW(session, nullptr, &stop.p, EVENT_TRACE_CONTROL_STOP);
        if (stopped) error("cleanup_StopTrace", stopped);
        return error("OpenTraceW", saved);
    }
    HANDLE thread = CreateThread(nullptr, 0, consume, nullptr, 0, nullptr);
    if (!thread) {
        const auto saved = GetLastError();
        Properties stop;
        const auto stopped = ControlTraceW(session, nullptr, &stop.p, EVENT_TRACE_CONTROL_STOP);
        if (stopped) error("cleanup_StopTrace", stopped);
        CloseTrace(consumer);
        return error("CreateThread", saved);
    }
    std::printf("{\"event\":\"ready\",\"session\":\"Probe1297-UNC-TCP\",\"seconds\":%u}\n", seconds);
    std::fflush(stdout);
    // Independent deadline; parent loss cannot leave this session running normally.
    Sleep(seconds * 1000);
    Properties stop;
    const auto stop_code = ControlTraceW(session, nullptr, &stop.p, EVENT_TRACE_CONTROL_STOP);
    const auto waited = WaitForSingleObject(thread, 8000);
    if (waited != WAIT_OBJECT_0) {
        CloseTrace(consumer); // Cancel this consumer only; no negative verdict.
        error("drain_timeout", waited);
        // Avoid destructing callback state while it could still be in use.
        ExitProcess(3);
    }
    CloseHandle(thread);
    const auto close_code = CloseTrace(consumer);
    const bool complete = !stop_code && !process_code && !close_code && !unsupported &&
        !stop.p.EventsLost && !stop.p.LogBuffersLost && !stop.p.RealTimeBuffersLost;
    std::printf("{\"event\":\"observation\",\"complete\":%s,\"matched\":%llu,"
        "\"attempts\":%llu,\"unsupported\":%llu,\"events_lost\":%lu,"
        "\"log_buffers_lost\":%lu,\"realtime_buffers_lost\":%lu,"
        "\"stop_code\":%lu,\"process_code\":%lu,\"close_code\":%lu,\"records\":[",
        complete ? "true" : "false", matched, attempts, unsupported,
        stop.p.EventsLost, stop.p.LogBuffersLost, stop.p.RealTimeBuffersLost,
        stop_code, process_code.load(), close_code);
    bool first = true;
    for (const auto& entry : counts) {
        std::printf("%s{\"pid\":%u,\"port\":%u,\"opcode\":%u,\"count\":%llu}",
            first ? "" : ",", std::get<0>(entry.first), std::get<1>(entry.first),
            std::get<2>(entry.first), entry.second);
        first = false;
    }
    std::printf("]}\n");
    return complete ? 0 : 3;
}
