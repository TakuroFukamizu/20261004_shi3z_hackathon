// RoverC Pro driver over the Core2 Port A (external I2C). Own implementation:
// the vendor M5-RoverC library re-inits Wire and fights M5Unified.
#pragma once
#include <M5Unified.h>
#include "config.h"
#include "mecanum.h"

namespace rover {

inline bool found        = false;
inline bool moving       = false;
inline uint32_t deadline = 0;
inline int8_t wheels[4]  = {0, 0, 0, 0};

inline bool writeWheels(const int8_t w[4])
{
    return M5.Ex_I2C.writeRegister(ROVER_ADDR, 0x00, (const uint8_t*)w, 4, ROVER_I2C_FREQ);
}

inline bool stop()
{
    memset(wheels, 0, sizeof(wheels));
    moving = false;
    return writeWheels(wheels);
}

inline void begin()
{
    i2c_port_t port = (M5.In_I2C.getPort() == I2C_NUM_0) ? I2C_NUM_1 : I2C_NUM_0;
    M5.Ex_I2C.begin(port, ROVER_SDA_PIN, ROVER_SCL_PIN);
    found = M5.Ex_I2C.scanID(ROVER_ADDR, ROVER_I2C_FREQ);
    if (found) stop();
    else Serial.println("[rover] RoverC (0x38) not found on Port A: wheels disabled");
}

// Drive for `ms` milliseconds, then stop automatically (watchdog).
inline bool drive(int x, int y, int rot, int ms)
{
    if (!found) return false;
    mecanum::mix(x, y, rot, wheels);
    ms       = constrain(ms, 1, DRIVE_MAX_MS);
    deadline = millis() + (uint32_t)ms;
    moving   = true;
    return writeWheels(wheels);
}

inline bool servo(int ch, int angle)
{
    if (!found || ch < 0 || ch > 1) return false;
    return M5.Ex_I2C.writeRegister8(ROVER_ADDR, 0x10 + ch, (uint8_t)constrain(angle, 0, 180), ROVER_I2C_FREQ);
}

// 0 = open, 100 = closed
inline bool grip(int percent)
{
    percent = constrain(percent, 0, 100);
    return servo(GRIPPER_CH, GRIPPER_OPEN_ANGLE + (GRIPPER_CLOSE_ANGLE - GRIPPER_OPEN_ANGLE) * percent / 100);
}

inline void tick()
{
    if (moving && (int32_t)(millis() - deadline) >= 0) stop();
}

}  // namespace rover
