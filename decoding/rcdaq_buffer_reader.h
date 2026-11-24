#pragma once
// Decode selected channel waveforms from complete RC disk buffers.
#include <Event/buffer.h>
#include <Event/Event.h>
#include <Event/EventTypes.h>
#include <Event/packet.h>
#include <vector>
#include <memory>
#include <fstream>
#include <stdexcept>
#include <cstdint>
#include <cstring>

namespace DQMLive {
struct RCWave {
    unsigned long long timestamp = 0;
    int samples = 0;
    std::vector<short> adc, toa, tot; // channel-major; includes sample zero
};

struct RCBlock {
    unsigned long long next = 0;
    int events = 0;
    bool endRun = false;
    std::vector<RCWave> waves;
};

inline RCBlock readRC(const std::string& filename, unsigned long long offset, int run,
                      const std::vector<int>& channels, bool timing = false) {
    RCBlock result;
    result.next = offset;
    std::ifstream input(filename, std::ios::binary);
    if (!input)
        return result;
    input.seekg(0, std::ios::end);
    auto size = input.tellg();
    if (size < 0 || static_cast<unsigned long long>(size) < offset)
        throw std::runtime_error("RC input truncated");
    if (static_cast<unsigned long long>(size) - offset < 8192)
        return result;
    input.seekg(offset);
    uint32_t head[2];
    input.read(reinterpret_cast<char*>(head), 8);
    const auto valid = [](uint32_t m) {
        return m == BUFFERMARKER || m == ONCSBUFFERMARKER || m == GZBUFFERMARKER ||
            m == LZO1XBUFFERMARKER || m == LZO1CBUFFERMARKER || m == LZO2ABUFFERMARKER ||
            m == BZ2BUFFERMARKER;
    };
    uint32_t length = head[0];
    if (!valid(head[1])) {
        if (!valid(buffer::u4swap(head[1])))
            throw std::runtime_error("Unknown RC buffer marker at " + std::to_string(offset));
        length = buffer::u4swap(length);
    }
    if (length < 16 || length > 256 * 1024 * 1024)
        throw std::runtime_error("Invalid RC buffer length");
    const size_t bytes = ((size_t(length) + 8191) / 8192) * 8192;
    if (static_cast<unsigned long long>(size) - offset < bytes)
        return result;
    std::vector<PHDWORD> data(bytes / 4);
    input.seekg(offset);
    if (!input.read(reinterpret_cast<char*>(data.data()), bytes))
        return result;
    buffer* raw = nullptr;
    if (buffer::makeBuffer(data.data(), data.size(), &raw) != 0 || !raw)
        throw std::runtime_error("Cannot decode RC buffer");
    std::unique_ptr<buffer> block(raw);
    while (auto* e = block->getEvent()) {
        std::unique_ptr<Event> event(e);
        ++result.events;
        if (event->getRunNumber() != run)
            throw std::runtime_error("RC input run mismatch");
        if (event->getEvtType() == ENDRUNEVENT)
            result.endRun = true;
        if (event->getEvtType() != DATAEVENT)
            continue;
        std::unique_ptr<Packet> packet(event->getPacket(12001));
        if (!packet)
            continue;
        if (packet->getHitFormat() != 302)
            throw std::runtime_error("Expected GCROC packet format 302");
        const int count = packet->iValue(0, "NR_WF"), nc = packet->iValue(0, "CHANNELS");
        for (int w = 0; w < count; ++w) {
            const int n = packet->iValue(w, "SAMPLESIZE");
            if (n < 1 || n > 40)
                throw std::runtime_error("GCROC waveform length outside 1..40");
            RCWave wave;
            wave.samples = n;
            wave.timestamp = packet->lValue(w, 0, 0);
            for (int ch : channels) {
                if (ch < 0 || ch >= nc)
                    throw std::runtime_error("GCROC mapped channel outside packet");
                for (int s = 0; s < n; ++s) {
                    wave.adc.push_back(packet->iValue(w, s, ch));
                    if (timing) {
                        wave.toa.push_back(packet->iValue(w, s, ch, "TOA"));
                        wave.tot.push_back(packet->iValue(w, s, ch, "TOT"));
                    }
                }
            }
            result.waves.push_back(std::move(wave));
        }
    }
    result.next = offset + bytes;
    return result;
}
}
