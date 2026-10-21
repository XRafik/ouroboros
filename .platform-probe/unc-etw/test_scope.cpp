#include "tcp_scope.hpp"
#include <cassert>

int main() {
    using namespace probe1297;
    const std::array<unsigned char, 4> target{127, 39, 4, 51};
    const std::array<std::uint16_t, 3> ports{50000, 50001, 50002};
    std::array<unsigned char, 40> data{};
    data[0] = 4; // SMB redirector SYSTEM must not be filtered by child PID.
    std::memcpy(data.data() + 8, target.data(), 4);
    data[12] = 127; data[15] = 1;
    data[16] = 1; data[17] = 189; // network-order 445
    Record record;
    assert(decode(2, 12, data.data(), data.size(), target, ports, record) == Decode::match);
    assert(record.pid == 4 && record.port == 445 && attempt(record.opcode));
    data[8] = 192;
    assert(decode(2, 12, data.data(), data.size(), target, ports, record) == Decode::ignore);
    std::memcpy(data.data() + 12, target.data(), 4);
    data[18] = 0; data[19] = 139;
    assert(decode(2, 11, data.data(), data.size(), target, ports, record) == Decode::match);
    assert(record.port == 139 && !attempt(record.opcode));
    data[19] = 80; // same target, unrelated port: never retained
    assert(decode(2, 11, data.data(), data.size(), target, ports, record) == Decode::ignore);
    assert(decode(3, 12, data.data(), data.size(), target, ports, record) == Decode::unsupported);
    assert(decode(2, 12, data.data(), 19, target, ports, record) == Decode::unsupported);
    assert(decode(2, 17, data.data(), 4, target, ports, record) == Decode::unsupported);
    assert(decode(2, 28, data.data(), data.size(), target, ports, record) == Decode::ignore);
}
