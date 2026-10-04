#pragma once
// ---- StackChan body on Core2 (M-Bus positions 21/22) ----
#define SERVO_TX_PIN 27
#define SERVO_RX_PIN 19
#define SERVO_BAUD 1000000
#define YAW_SERVO_ID 1
#define PITCH_SERVO_ID 2
#define YAW_DEFAULT_ZERO 460
#define PITCH_DEFAULT_ZERO 620
// Head limits in degrees. Pitch extremes can stall and damage the servo.
#define YAW_LIMIT_DEG 120
#define PITCH_MIN_DEG 5
#define PITCH_MAX_DEG 85

// ---- RoverC Pro on Port A (red Grove) ----
#define ROVER_SDA_PIN 32
#define ROVER_SCL_PIN 33
#define ROVER_ADDR 0x38
#define ROVER_I2C_FREQ 100000
#define GRIPPER_CH 0
#define GRIPPER_OPEN_ANGLE 10
#define GRIPPER_CLOSE_ANGLE 90
#define DRIVE_DEFAULT_MS 500
#define DRIVE_MAX_MS 5000

// ---- Network ----
#define AP_SSID "stackchan-rover"
#define AP_PASS "stackchan"
#define MDNS_NAME "stackchan"
#define SPEAK_MAX_BYTES (2 * 1024 * 1024)
#define SPEAKER_VOLUME 200
