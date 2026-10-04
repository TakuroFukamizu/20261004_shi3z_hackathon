// StackChan body (K151) on Core2: servo power, serial-bus servos, head motion.
// ScsServo is adapted from StackChan-BSP M5StackChan.cpp (MIT, M5Stack), which
// cannot be used as-is on Core2 because it hard-codes the servo UART to GPIO6/7.
#pragma once
#include <M5Unified.h>
#include <drivers/FTServo_Arduino/src/SCSCL.h>
#include <drivers/PY32IOExpander/PY32IOExpander.hpp>
#include <utils/motion/motion.h>
#include <utils/settings/settings.h>
#include "config.h"

namespace head {

inline SCSCL bus;
inline m5::PY32IOExpander_Class ioe;
inline stackchan::motion::Motion motion;
inline bool bodyFound   = false;  // IO expander answered
inline bool servosFound = false;  // both servos answered a ping
inline bool calibrated  = false;

class ScsServo : public stackchan::motion::Servo {
public:
    ScsServo(int id, int defaultZero, uitk_intl::Vector2i angleLimit, const char* key, bool pwm)
        : _id(id), _zero(defaultZero), _key(key), _pwm(pwm)
    {
        set_angle_limit(angleLimit);
    }

    void init() override
    {
        Settings s("servo", false);
        int z = s.GetInt(_key, -1);
        if (z >= 0 && z <= 1000) _zero = z;
        Servo::init();
    }

    void set_angle_impl(int angle) override
    {
        int raw = _zero + angle * 16 / 5 / 10;  // 1 step = 0.3125 deg, angle unit = 0.1 deg
        raw     = uitk_intl::clamp(raw, 0, 1000);
        mode(0);
        bus.WritePos(_id, raw, 20, 0);
    }

    int getCurrentAngle() override
    {
        int raw = bus.ReadPos(_id);
        if (raw < 0 || raw > 1000) {
            return uitk_intl::clamp(Servo::getCurrentAngle(), getAngleLimit().x, getAngleLimit().y);
        }
        return uitk_intl::clamp((raw - _zero) * 5 * 10 / 16, getAngleLimit().x, getAngleLimit().y);
    }

    bool is_moving_impl() override { return bus.ReadMove(_id) != 0; }

    void setTorqueEnabled(bool enabled) override
    {
        Servo::setTorqueEnabled(enabled);
        bus.EnableTorque(_id, enabled ? 1 : 0);
    }

    bool getTorqueEnabled() override { return bus.ReadToqueEnable(_id) > 0; }

    void setCurrentAngleAsZero() override
    {
        int raw = bus.ReadPos(_id);
        if (raw < 0 || raw > 1000) return;
        _zero = raw;
        Settings s("servo", true);
        s.SetInt(_key, _zero);
    }

    void rotate(int velocity) override
    {
        if (!_pwm) return;
        velocity = uitk_intl::clamp(velocity, -1000, 1000);
        mode(1);
        bus.WritePWM(_id, uitk_intl::map_range(velocity, 0, 1000, 0, 1023));
    }

private:
    void mode(int m)
    {
        if (m == _mode) return;
        bus.SwitchMode(_id, (uint8_t)m);
        _mode = m;
    }
    int _id;
    int _zero;
    std::string _key;
    bool _pwm;
    int _mode = 0;
};

inline void begin()
{
    // The PY32 IO expander boots slowly; retry for a while.
    for (int i = 0; i < 6 && !bodyFound; i++) {
        delay(200);
        bodyFound = ioe.begin();
    }
    if (!bodyFound) {
        Serial.println("[head] IO expander (0x6F) not found: head disabled");
        return;
    }
    ioe.setDirection(0, true);  // servo power enable
    ioe.setPullMode(0, m5::PY32IOExpander_Class::pull_up);
    ioe.digitalWrite(0, true);
    delay(300);

    bus.begin(UART_NUM_1, SERVO_BAUD, SERVO_TX_PIN, SERVO_RX_PIN);
    servosFound = bus.Ping(YAW_SERVO_ID) == YAW_SERVO_ID && bus.Ping(PITCH_SERVO_ID) == PITCH_SERVO_ID;
    if (!servosFound) {
        Serial.printf("[head] servos did not answer on TX=%d RX=%d: head disabled\n", SERVO_TX_PIN, SERVO_RX_PIN);
        return;
    }

    uitk_intl::ui_hal::on_delay([](uint32_t ms) { delay(ms); });
    uitk_intl::ui_hal::on_get_tick([]() { return (uint32_t)millis(); });

    motion.init(
        std::make_unique<ScsServo>(YAW_SERVO_ID, YAW_DEFAULT_ZERO, uitk_intl::Vector2i(-1280, 1280), "zero_pos_1", true),
        std::make_unique<ScsServo>(PITCH_SERVO_ID, PITCH_DEFAULT_ZERO, uitk_intl::Vector2i(0, 900), "zero_pos_2", false));

    Settings s("robot", false);
    calibrated = s.GetBool("head_cal", false);
    if (!calibrated) motion.setAutoTorqueReleaseEnabled(false);  // stays limp until calibrated
}

inline bool ready() { return servosFound && calibrated; }

// useCurrentPose=true: store the pose the head is in now as home (0,0).
// useCurrentPose=false: trust the BSP default zero positions.
inline void calibrate(bool useCurrentPose)
{
    if (!servosFound) return;
    if (useCurrentPose) motion.setCurrentPostionAsHome();
    Settings s("robot", true);
    s.SetBool("head_cal", true);
    calibrated = true;
    motion.setAutoTorqueReleaseEnabled(true);
}

inline void move(float yawDeg, float pitchDeg, int speed)
{
    yawDeg   = constrain(yawDeg, -YAW_LIMIT_DEG, YAW_LIMIT_DEG);
    pitchDeg = constrain(pitchDeg, PITCH_MIN_DEG, PITCH_MAX_DEG);
    motion.move((int)(yawDeg * 10), (int)(pitchDeg * 10), constrain(speed, 1, 1000));
}

}  // namespace head
