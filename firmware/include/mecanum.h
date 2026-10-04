// Mecanum wheel mixing for RoverC. Pure function so it can be tested on the host.
#pragma once
#include <stdint.h>
#include <stdlib.h>

namespace mecanum {

inline int8_t clamp100(int v) { return (int8_t)(v > 100 ? 100 : (v < -100 ? -100 : v)); }

// x: strafe right(+), y: forward(+), rot: rotate(+), each -100..100.
// out[4] = RoverC registers 0x00..0x03.
inline void mix(int x, int y, int rot, int8_t out[4])
{
    x   = clamp100(x);
    y   = clamp100(y);
    rot = clamp100(rot);
    if (rot != 0) {
        x = x * (100 - abs(rot)) / 100;
        y = y * (100 - abs(rot)) / 100;
    }
    out[0] = clamp100(y + x - rot);
    out[1] = clamp100(y - x + rot);
    out[2] = clamp100(y - x - rot);
    out[3] = clamp100(y + x + rot);
}

}  // namespace mecanum
