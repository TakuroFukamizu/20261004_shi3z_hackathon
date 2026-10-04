// Plays 16-bit PCM WAV received from the PC and derives a mouth-open ratio for lip sync.
#pragma once
#include <M5Unified.h>
#include "config.h"

namespace voice {

inline uint8_t* buf         = nullptr;  // owned WAV buffer
inline const int16_t* pcm   = nullptr;
inline size_t samples       = 0;  // total int16 values (all channels)
inline uint32_t rate        = 16000;
inline int channels         = 1;
inline uint32_t startMs     = 0;
inline bool playing         = false;

inline void stop()
{
    M5.Speaker.stop();
    playing = false;
    if (buf) {
        delay(60);  // let the speaker task drop its reference
        free(buf);
        buf = nullptr;
    }
}

static inline uint32_t le32(const uint8_t* p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24); }
static inline uint16_t le16(const uint8_t* p) { return p[0] | (p[1] << 8); }

// Takes ownership of `data` (malloc'd). Returns nullptr on success, else an error string.
inline const char* playWav(uint8_t* data, size_t len)
{
    stop();
    const char* err = nullptr;
    size_t dataOff = 0, dataLen = 0;
    int bits = 0, fmt = 0;
    if (len < 12 || memcmp(data, "RIFF", 4) || memcmp(data + 8, "WAVE", 4)) {
        err = "not a WAV file";
    } else {
        for (size_t p = 12; p + 8 <= len;) {
            uint32_t sz = le32(data + p + 4);
            if (!memcmp(data + p, "fmt ", 4) && p + 24 <= len) {
                fmt      = le16(data + p + 8);
                channels = le16(data + p + 10);
                rate     = le32(data + p + 12);
                bits     = le16(data + p + 22);
            } else if (!memcmp(data + p, "data", 4)) {
                dataOff = p + 8;
                dataLen = (sz > len - dataOff) ? len - dataOff : sz;
                break;
            }
            p += 8 + sz + (sz & 1);
        }
        if (!dataOff || !dataLen) err = "no data chunk";
        else if (fmt != 1 || bits != 16 || channels < 1 || channels > 2) err = "need 16-bit PCM, mono or stereo";
    }
    if (err) {
        free(data);
        return err;
    }
    memmove(data, data + dataOff, dataLen);  // align PCM to buffer start
    buf     = data;
    pcm     = (const int16_t*)buf;
    samples = dataLen / 2;
    M5.Speaker.playRaw(pcm, samples, rate, channels == 2, 1, 0, true);
    startMs = millis();
    playing = true;
    return nullptr;
}

// Call every ~30 ms. Returns mouth open ratio 0..1.
inline float tick()
{
    if (!playing) return 0.0f;
    size_t idx = (size_t)((uint64_t)(millis() - startMs) * rate / 1000) * channels;
    if (idx >= samples) {
        if (!M5.Speaker.isPlaying()) stop();
        return 0.0f;
    }
    size_t n = min((size_t)480, samples - idx);
    uint32_t sum = 0;
    for (size_t i = 0; i < n; i++) sum += abs(pcm[idx + i]);
    float r = (float)(sum / (n ? n : 1)) / 5000.0f;
    return r > 1.0f ? 1.0f : r;
}

}  // namespace voice
