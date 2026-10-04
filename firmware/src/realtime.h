// Low-latency UDP channel for the PC hub (client/stackchan_hub.py). Included from main.cpp
// after handleCommand() and fillStatus().
//
// PC -> robot  (port RT_PORT), one JSON command per datagram:
//   {"sid":S,"seq":N,"cmd":...}  reliable: executed once, answered {"ack":N,...}; retransmits get the same answer
//   {"cmd":...}                  stream: executed, no answer (latest wins: head targets, drive refresh)
//   {"cmd":"ping"}               keeps the sender registered for telemetry
// robot -> PC  every RT_TELEMETRY_MS to the last sender:
//   {"t":"state",...,"ev":[{"id":..,"e":"speech_end","a":clip},...]}  the last events ride along
//   in every state packet, so a lost datagram does not lose an event.
#pragma once
#include <AsyncUDP.h>

namespace rt {

struct Ev {
    uint32_t id;
    char name[16];
    int32_t arg;
};

inline AsyncUDP udp;
inline IPAddress client;
inline uint16_t clientPort  = 0;
inline uint32_t clientSeen  = 0;
inline uint32_t nextEventId = 1;
inline Ev events[RT_EVENT_RING];
inline portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;

struct Reply {
    uint32_t sid = 0, seq = 0;
    String text;
};
inline Reply replies[8];  // recent answers, for retransmitted commands
inline int replyNext = 0;

inline bool hasClient() { return clientPort && millis() - clientSeen < RT_CLIENT_TIMEOUT_MS; }

inline void event(const char* name, int32_t arg = 0)
{
    portENTER_CRITICAL(&mux);
    Ev& e = events[nextEventId % RT_EVENT_RING];
    e.id  = nextEventId++;
    strlcpy(e.name, name, sizeof(e.name));
    e.arg = arg;
    portEXIT_CRITICAL(&mux);
}

inline void onPacket(AsyncUDPPacket& p)
{
    JsonDocument req;
    if (deserializeJson(req, p.data(), p.length())) return;
    client     = p.remoteIP();
    clientPort = p.remotePort();
    clientSeen = millis();

    const char* cmd = req["cmd"] | "";
    if (!strcmp(cmd, "ping")) return;
    uint32_t sid = req["sid"] | 0u, seq = req["seq"] | 0u;
    if (seq) {
        for (auto& r : replies) {
            if (r.seq == seq && r.sid == sid) {  // retransmission: answer again, do not run twice
                p.write((const uint8_t*)r.text.c_str(), r.text.length());
                return;
            }
        }
    }
    JsonDocument res;
    handleCommand(req, res);
    if (!seq) return;
    res["ack"] = seq;
    Reply& r   = replies[replyNext];
    replyNext  = (replyNext + 1) % 8;
    r.sid      = sid;
    r.seq      = seq;
    r.text     = "";
    serializeJson(res, r.text);
    p.write((const uint8_t*)r.text.c_str(), r.text.length());
}

inline void begin()
{
    if (udp.listen(RT_PORT)) {
        udp.onPacket(onPacket);
        Serial.printf("[rt] udp %d\n", RT_PORT);
    }
}

// Call from loop() with the command lock held.
inline void tick()
{
    static uint32_t last = 0, lastBattery = 0;
    static int battery = -1;
    if (millis() - lastBattery > 2000 || battery < 0) {
        lastBattery = millis();
        battery     = M5.Power.getBatteryLevel();
    }
    if (!hasClient() || millis() - last < RT_TELEMETRY_MS) return;
    last = millis();

    JsonDocument st;
    st["t"]          = "state";
    st["ms"]         = millis();
    st["speaking"]   = voice::playing;
    st["clip"]       = voice::clipId;
    st["rover"]      = rover::found || roverLinked();
    st["moving"]     = rover::moving;
    st["calibrated"] = head::calibrated;
    st["battery"]    = battery;
    st["rssi"]       = WiFi.RSSI();
    if (head::servosFound) {
        auto a      = head::motion.getCurrentAngles();
        st["yaw"]   = a.x / 10.0f;
        st["pitch"] = a.y / 10.0f;
    }
    JsonArray ev = st["ev"].to<JsonArray>();
    portENTER_CRITICAL(&mux);
    uint32_t first = nextEventId > RT_EVENT_SEND ? nextEventId - RT_EVENT_SEND : 1;
    Ev copy[RT_EVENT_SEND];
    int n = 0;
    for (uint32_t id = first; id < nextEventId; id++) copy[n++] = events[id % RT_EVENT_RING];
    portEXIT_CRITICAL(&mux);
    for (int i = 0; i < n; i++) {
        JsonObject o = ev.add<JsonObject>();
        o["id"]      = copy[i].id;
        o["e"]       = copy[i].name;
        o["a"]       = copy[i].arg;
    }
    String out;
    serializeJson(st, out);
    udp.writeTo((const uint8_t*)out.c_str(), out.length(), client, clientPort);
}

}  // namespace rt
