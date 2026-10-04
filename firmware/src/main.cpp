// StackChan (K151 body + Core2) on RoverC Pro: face, voice, head, wheels, gripper.
// Control: JSON commands over HTTP (POST /cmd, POST /speak) or one JSON per line on USB serial.
#include <Arduino.h>
#include <M5Unified.h>
#include <Avatar.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <esp_http_server.h>
#include "config.h"
#include "head.h"
#include "rover.h"
#include "voice.h"
#if __has_include("secrets.h")
#include "secrets.h"
#endif

static m5avatar::Avatar avatar;
static SemaphoreHandle_t gLock;  // serialises command execution and the loop tick
static String ipText = "-";
static String speechText;        // must outlive avatar.setSpeechText()

struct Lock {
    Lock() { xSemaphoreTakeRecursive(gLock, portMAX_DELAY); }
    ~Lock() { xSemaphoreGiveRecursive(gLock); }
};

static void say(const char* text)
{
    speechText = text ? text : "";
    avatar.setSpeechText(speechText.c_str());
}

static bool setExpression(const char* name)
{
    using m5avatar::Expression;
    static const struct { const char* n; Expression e; } table[] = {
        {"neutral", Expression::Neutral}, {"happy", Expression::Happy}, {"angry", Expression::Angry},
        {"sad", Expression::Sad},         {"doubt", Expression::Doubt}, {"sleepy", Expression::Sleepy},
    };
    for (auto& t : table) {
        if (!strcasecmp(name, t.n)) {
            avatar.setExpression(t.e);
            return true;
        }
    }
    return false;
}

static void fillStatus(JsonDocument& res)
{
    res["ip"]              = ipText;
    res["rover"]           = rover::found;
    res["body"]            = head::bodyFound;
    res["servos"]          = head::servosFound;
    res["head_calibrated"] = head::calibrated;
    res["speaking"]        = voice::playing;
    res["moving"]          = rover::moving;
    res["battery"]         = M5.Power.getBatteryLevel();
    res["free_psram"]      = ESP.getFreePsram();
    if (head::servosFound) {
        auto a       = head::motion.getCurrentAngles();
        res["yaw"]   = a.x / 10.0f;
        res["pitch"] = a.y / 10.0f;
    }
}

// Executes one command. Fills `res` with {"ok":true,...} or {"ok":false,"error":"..."}.
static void handleCommand(JsonDocument& req, JsonDocument& res)
{
    Lock lock;
    const char* cmd = req["cmd"] | "";
    const char* err = nullptr;

    if (!strcmp(cmd, "status")) {
        fillStatus(res);
    } else if (!strcmp(cmd, "face")) {
        if (req["expression"].is<const char*>() && !setExpression(req["expression"])) err = "unknown expression";
        if (req["text"].is<const char*>()) say(req["text"]);
    } else if (!strcmp(cmd, "head")) {
        if (!head::servosFound) err = "head servos not found";
        else if (!head::calibrated) err = "head not calibrated: send {\"cmd\":\"calibrate\"} first";
        else head::move(req["yaw"] | 0.0f, req["pitch"] | 45.0f, req["speed"] | 500);
    } else if (!strcmp(cmd, "calibrate")) {
        if (!head::servosFound) err = "head servos not found";
        else head::calibrate(!(req["default"] | false));
    } else if (!strcmp(cmd, "torque")) {
        if (!head::servosFound) err = "head servos not found";
        else head::motion.setTorqueEnabled(req["on"] | false);
    } else if (!strcmp(cmd, "drive")) {
        if (!rover::drive(req["x"] | 0, req["y"] | 0, req["rot"] | 0, req["ms"] | DRIVE_DEFAULT_MS)) err = "rover not responding";
    } else if (!strcmp(cmd, "grip")) {
        if (!rover::grip(req["percent"] | 0)) err = "rover not responding";
    } else if (!strcmp(cmd, "servo")) {
        if (!rover::servo(req["ch"] | 0, req["angle"] | 90)) err = "rover not responding";
    } else if (!strcmp(cmd, "stop")) {
        rover::stop();
        voice::stop();
        if (head::servosFound) head::motion.stop();
    } else if (!strcmp(cmd, "volume")) {
        M5.Speaker.setVolume(constrain(req["value"] | SPEAKER_VOLUME, 0, 255));
    } else if (!strcmp(cmd, "beep")) {
        M5.Speaker.tone(req["freq"] | 880, req["ms"] | 200);
    } else {
        err = "unknown cmd";
    }

    res["ok"] = (err == nullptr);
    if (err) res["error"] = err;
}

// ---------------------------------------------------------------- HTTP

static esp_err_t sendJson(httpd_req_t* r, JsonDocument& doc, const char* status = "200 OK")
{
    String out;
    serializeJson(doc, out);
    httpd_resp_set_status(r, status);
    httpd_resp_set_type(r, "application/json");
    return httpd_resp_send(r, out.c_str(), out.length());
}

static esp_err_t sendError(httpd_req_t* r, const char* msg)
{
    JsonDocument doc;
    doc["ok"]    = false;
    doc["error"] = msg;
    return sendJson(r, doc, "400 Bad Request");
}

static bool recvAll(httpd_req_t* r, uint8_t* dst, size_t len)
{
    size_t got = 0;
    while (got < len) {
        int n = httpd_req_recv(r, (char*)dst + got, len - got);
        if (n == HTTPD_SOCK_ERR_TIMEOUT) continue;
        if (n <= 0) return false;
        got += n;
    }
    return true;
}

static esp_err_t onCmd(httpd_req_t* r)
{
    char body[1024];
    if (r->content_len == 0 || r->content_len >= sizeof(body)) return sendError(r, "body must be 1..1023 bytes of JSON");
    if (!recvAll(r, (uint8_t*)body, r->content_len)) return ESP_FAIL;
    body[r->content_len] = 0;
    JsonDocument req, res;
    if (deserializeJson(req, body)) return sendError(r, "invalid JSON");
    handleCommand(req, res);
    return sendJson(r, res, res["ok"] ? "200 OK" : "400 Bad Request");
}

static esp_err_t onSpeak(httpd_req_t* r)
{
    if (r->content_len < 44 || r->content_len > SPEAK_MAX_BYTES) return sendError(r, "WAV must be 44 bytes .. 2 MB");
    {
        Lock lock;
        voice::stop();  // free the previous clip before allocating
    }
    uint8_t* data = (uint8_t*)ps_malloc(r->content_len);
    if (!data) return sendError(r, "out of memory");
    if (!recvAll(r, data, r->content_len)) {
        free(data);
        return ESP_FAIL;
    }
    Lock lock;
    const char* err = voice::playWav(data, r->content_len);
    if (err) return sendError(r, err);
    JsonDocument res;
    res["ok"]      = true;
    res["seconds"] = (float)voice::samples / voice::channels / voice::rate;
    return sendJson(r, res);
}

static esp_err_t onStatus(httpd_req_t* r)
{
    JsonDocument res;
    {
        Lock lock;
        fillStatus(res);
    }
    res["ok"] = true;
    return sendJson(r, res);
}

static void startHttp()
{
    httpd_config_t cfg   = HTTPD_DEFAULT_CONFIG();
    cfg.stack_size       = 8192;
    cfg.recv_wait_timeout = 10;
    httpd_handle_t server = nullptr;
    if (httpd_start(&server, &cfg) != ESP_OK) {
        Serial.println("[http] start failed");
        return;
    }
    static const httpd_uri_t routes[] = {
        {.uri = "/", .method = HTTP_GET, .handler = onStatus, .user_ctx = nullptr},
        {.uri = "/status", .method = HTTP_GET, .handler = onStatus, .user_ctx = nullptr},
        {.uri = "/cmd", .method = HTTP_POST, .handler = onCmd, .user_ctx = nullptr},
        {.uri = "/speak", .method = HTTP_POST, .handler = onSpeak, .user_ctx = nullptr},
    };
    for (auto& rt : routes) httpd_register_uri_handler(server, &rt);
}

static void startWifi()
{
#ifdef WIFI_SSID
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
    if (WiFi.status() == WL_CONNECTED) {
        ipText = WiFi.localIP().toString();
    }
#endif
    if (ipText == "-") {
        WiFi.mode(WIFI_AP);
        WiFi.softAP(AP_SSID, AP_PASS);
        ipText = WiFi.softAPIP().toString();
        Serial.printf("[wifi] access point \"%s\" password \"%s\"\n", AP_SSID, AP_PASS);
    }
    MDNS.begin(MDNS_NAME);
    Serial.printf("[wifi] http://%s/  (http://%s.local/)\n", ipText.c_str(), MDNS_NAME);
}

// ---------------------------------------------------------------- main

void setup()
{
    auto cfg         = M5.config();
    cfg.internal_imu = false;  // the body's touch IC shares address 0x68 with the Core2 IMU
    M5.begin(cfg);
    Serial.begin(115200);
    gLock = xSemaphoreCreateRecursiveMutex();

    M5.Speaker.setVolume(SPEAKER_VOLUME);
    rover::begin();
    head::begin();

    avatar.setSpeechFont(&fonts::lgfxJapanGothicP_16);
    avatar.init();
    say("WiFi...");

    startWifi();
    startHttp();
    say(ipText.c_str());
    M5.Speaker.tone(1320, 120);
    Serial.printf("[boot] rover=%d body=%d servos=%d head_calibrated=%d\n", rover::found, head::bodyFound,
                  head::servosFound, head::calibrated);
}

static void pollSerial()
{
    static String line;
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\n' || c == '\r') {
            if (line.length()) {
                JsonDocument req, res;
                if (deserializeJson(req, line)) {
                    res["ok"]    = false;
                    res["error"] = "invalid JSON";
                } else {
                    handleCommand(req, res);
                }
                serializeJson(res, Serial);
                Serial.println();
                line = "";
            }
        } else if (line.length() < 1000) {
            line += c;
        }
    }
}

void loop()
{
    M5.update();
    pollSerial();
    {
        Lock lock;
        rover::tick();
        static bool wasPlaying = false;
        float mouth            = voice::tick();
        if (voice::playing || wasPlaying) avatar.setMouthOpenRatio(mouth);
        if (wasPlaying && !voice::playing) say("");  // clear the balloon when speech ends
        wasPlaying = voice::playing;
    }
    // Touch button A (left): emergency stop.
    if (M5.BtnA.wasPressed()) {
        JsonDocument req, res;
        req["cmd"] = "stop";
        handleCommand(req, res);
    }
    delay(30);
}
