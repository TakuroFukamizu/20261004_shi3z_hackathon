// Host test:  c++ -std=c++17 -I../include test_mecanum.cpp -o /tmp/t && /tmp/t
#include "mecanum.h"
#include <cassert>
#include <cstdio>

static void expect(int x, int y, int r, int a, int b, int c, int d)
{
    int8_t o[4];
    mecanum::mix(x, y, r, o);
    if (o[0] != a || o[1] != b || o[2] != c || o[3] != d) {
        printf("FAIL mix(%d,%d,%d) = %d %d %d %d\n", x, y, r, o[0], o[1], o[2], o[3]);
        exit(1);
    }
}

int main()
{
    expect(0, 0, 0, 0, 0, 0, 0);
    expect(0, 50, 0, 50, 50, 50, 50);        // forward: all wheels same
    expect(50, 0, 0, 50, -50, -50, 50);      // strafe: diagonal pairs
    expect(0, 0, 50, -50, 50, -50, 50);      // rotate: left/right opposite
    expect(0, 500, 0, 100, 100, 100, 100);   // input clamp
    expect(100, 100, 0, 100, 0, 0, 100);     // output clamp
    expect(0, 100, 100, -100, 100, -100, 100);  // full rotation cancels translation
    puts("OK");
    return 0;
}
