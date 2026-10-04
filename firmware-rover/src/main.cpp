// RoverC Pro controller on M5StickC Plus: wheels and gripper.
// Receives the same JSON commands as the Core2 (drive / grip / servo / stop)
// over ESP-NOW broadcast from the Core2, or one JSON per line on USB serial.
// No Wi-Fi settings needed: it hops channels until it hears the Core2 beacon.
#include <Arduino.h>
#include <M5Unified.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include "config.h"
#include "rover.h"

struct Packet {
    uint8_t len;
    char data[251];
};
static QueueHandle_t rxQueue;
static const uint8_t kBroadcast[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
static uint32_t lastHeardMs = 0;
static bool linked          = false;
static uint8_t channel      = 1;

static void onRecv(const esp_now_recv_info_t*, const uint8_t* data, int len)
{
    Packet p;
    if (len <= 0 || len > 250) return;
    p.len = (uint8_t)len;
    memcpy(p.data, data, len);
    p.data[len] = 0;
    xQueueSend(rxQueue, &p, 0);
}

static void setChannel(uint8_t ch)
{
    channel = ch;
    esp_wifi_set_promiscuous(true);
    esp_wifi_set_channel(ch, WIFI_SECOND_CHAN_NONE);
    esp_wifi_set_promiscuous(false);
}

static void draw()
{
    auto& d = M5.Display;
    d.fillScreen(!rover::found ? TFT_MAROON : (linked ? TFT_DARKGREEN : TFT_BLACK));
    d.setCursor(4, 4);
    d.setTextSize(2);
    d.printf("RoverC %s\n", rover::found ? "OK" : "NG");
    d.printf("%s\n", linked ? "LINKED" : "searching");
    d.setTextSize(1);
    d.printf("\n ch %d   BtnA: stop\n", channel);
}

static void handleCommand(JsonDocument& req, JsonDocument& res)
{
    const char* cmd = req["cmd"] | "";
    const char* err = nullptr;
    if (!strcmp(cmd, "drive")) {
        if (!rover::drive(req["x"] | 0, req["y"] | 0, req["rot"] | 0, req["ms"] | DRIVE_DEFAULT_MS)) err = "rover not responding";
    } else if (!strcmp(cmd, "grip")) {
        if (!rover::grip(req["percent"] | 0)) err = "rover not responding";
    } else if (!strcmp(cmd, "servo")) {
        if (!rover::servo(req["ch"] | 0, req["angle"] | 90)) err = "rover not responding";
    } else if (!strcmp(cmd, "stop")) {
        rover::stop();
    } else if (!strcmp(cmd, "status")) {
        res["rover"]   = rover::found;
        res["moving"]  = rover::moving;
        res["linked"]  = linked;
        res["channel"] = channel;
        res["battery"] = M5.Power.getBatteryLevel();
    } else {
        err = "unknown cmd";
    }
    res["ok"] = (err == nullptr);
    if (err) res["error"] = err;
}

static void handleText(const char* text, Print* replyTo)
{
    JsonDocument req, res;
    if (deserializeJson(req, text)) {
        res["ok"]    = false;
        res["error"] = "invalid JSON";
    } else if (!req["cmd"].is<const char*>()) {
        return;  // beacon
    } else {
        handleCommand(req, res);
    }
    if (replyTo) {
        serializeJson(res, *replyTo);
        replyTo->println();
    }
}

void setup()
{
    M5.begin();
    Serial.begin(115200);
    M5.Display.setRotation(1);
    rover::begin();

    rxQueue = xQueueCreate(8, sizeof(Packet));
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    setChannel(1);
    if (esp_now_init() == ESP_OK) {
        esp_now_peer_info_t peer = {};
        memcpy(peer.peer_addr, kBroadcast, 6);
        peer.channel = 0;
        peer.ifidx   = WIFI_IF_STA;
        esp_now_add_peer(&peer);
        esp_now_register_recv_cb(onRecv);
    } else {
        Serial.println("[espnow] init failed");
    }
    draw();
    Serial.printf("[boot] rover=%d\n", rover::found);
}

void loop()
{
    M5.update();
    rover::tick();

    Packet p;
    while (xQueueReceive(rxQueue, &p, 0) == pdTRUE) {
        lastHeardMs = millis();
        if (!linked) {
            linked = true;
            Serial.printf("[espnow] linked on channel %d\n", channel);
            draw();
        }
        handleText(p.data, nullptr);
    }

    if (linked && millis() - lastHeardMs > ROVER_LINK_TIMEOUT_MS) {
        linked = false;
        rover::stop();  // lost the Core2: never keep driving
        Serial.println("[espnow] link lost");
        draw();
    }

    static uint32_t lastHop = 0, lastBeat = 0;
    if (!linked && millis() - lastHop > 2 * BEACON_INTERVAL_MS + 100) {  // hop until the beacon is heard
        lastHop = millis();
        setChannel(channel % 13 + 1);
    }
    if (linked && millis() - lastBeat > 1000) {  // heartbeat so the Core2 knows we are here
        lastBeat = millis();
        static const char beat[] = "{\"rover\":true}";
        esp_now_send(kBroadcast, (const uint8_t*)beat, sizeof(beat) - 1);
    }

    static String line;
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\n' || c == '\r') {
            if (line.length()) handleText(line.c_str(), &Serial);
            line = "";
        } else if (line.length() < 500) {
            line += c;
        }
    }

    if (M5.BtnA.wasPressed()) rover::stop();
    delay(10);
}
