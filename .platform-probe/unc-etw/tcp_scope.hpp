#pragma once
// Portable decoder for the documented TcpIp v2 IPv4 common prefix.
// No packet bytes, process names, file paths, or authentication data are exposed.
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace probe1297 {
struct Record {
    std::uint32_t pid = 0;
    std::uint16_t port = 0;
    unsigned opcode = 0;
};
enum class Decode { ignore, match, unsupported };

inline bool attempt(unsigned op) {
    return op == 10 || op == 12 || op == 14 || op == 16;
}

inline Decode decode(unsigned version, unsigned op, const void* data, std::size_t n,
                     const std::array<unsigned char, 4>& target,
                     const std::array<std::uint16_t, 3>& control_ports, Record& out) {
    // Fail cannot be attributed: its documented schema has no addresses.
    if (op == 17) return Decode::unsupported;
    if (op >= 26 && op <= 34) return Decode::ignore; // explicit IPv4 experiment
    if (version != 2 || op < 10 || op > 18 || n < 20)
        return Decode::unsupported;
    const auto* p = static_cast<const unsigned char*>(data);
    const auto dport = static_cast<std::uint16_t>((p[16] << 8) | p[17]);
    const auto sport = static_cast<std::uint16_t>((p[18] << 8) | p[19]);
    auto wanted = [&control_ports](unsigned port) {
        if (port == 445 || port == 139) return true;
        for (auto control : control_ports) if (control && port == control) return true;
        return false;
    };
    const bool destination = std::memcmp(p + 8, target.data(), 4) == 0 && wanted(dport);
    const bool source = std::memcmp(p + 12, target.data(), 4) == 0 && wanted(sport);
    if (!destination && !source) return Decode::ignore;
    out.pid = std::uint32_t(p[0]) | (std::uint32_t(p[1]) << 8) |
              (std::uint32_t(p[2]) << 16) | (std::uint32_t(p[3]) << 24);
    out.port = destination ? dport : sport;
    out.opcode = op;
    return Decode::match;
}
} // namespace probe1297
