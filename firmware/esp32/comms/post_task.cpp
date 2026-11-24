#include <Arduino.h>
#include <WiFi.h>
#include <atomic>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

#include <time.h>

#include "../config.h"
#include "credentials.h"
#include "http_client.h"
#include "post_rules.h"
#include "post_queue.h"
#include "post_task.h"
#include "wifi_manager.h"

#if OTA_ENABLED
// defined in ota.ino, which pio_src/main.cpp includes before esp32.ino.
void checkAndApplyOTA();
#endif

namespace {

Mailbox            g_box;
SemaphoreHandle_t  g_lock = nullptr;
PostWatch          g_watch;
TaskHandle_t       g_task = nullptr;
const Credentials* g_creds = nullptr;

// the post task's own copy of the body, so the mailbox lock is held only for the copy
char g_work[TELEMETRY_BODY_MAX_BYTES];

std::atomic<int32_t>  g_rssi{0};
std::atomic<bool>     g_wifiUp{false};
std::atomic<uint32_t> g_failed{0};
std::atomic<uint32_t> g_ok{0};
std::atomic<uint32_t> g_dropped{0};
std::atomic<uint32_t> g_stackFree{POST_TASK_STACK_BYTES};
// a 401 or 403 came back, so the key is wrong and retrying will not fix it. cleared by a success
std::atomic<bool>     g_keyRejected{false};
// the hub is posting over plain HTTP (a bench build)
std::atomic<bool>     g_plain{false};
// a 409 came back: the server has seen a newer counter from this machine. cleared by a success
std::atomic<bool>     g_counterRejected{false};
// a 404 came back: the address is wrong. cleared by a success
std::atomic<bool>     g_addressWrong{false};

// wait in short steps so the beat keeps coming while the task is idle or backing off
void sleepBeating(uint32_t ms) {
    while (ms > 0) {
        uint32_t step = ms > 200 ? 200 : ms;
        vTaskDelay(pdMS_TO_TICKS(step));
        pwBeat(&g_watch, millis());
        ms -= step;
    }
}

void postTask(void*) {
    pwBeat(&g_watch, millis());

    // nothing is stored yet: the hub runs its sensors, panel and relays and posts nothing until it
    // is provisioned over the serial console (see provision.h). it never touches the radio.
    while (!g_creds || !g_creds->present) {
        Serial.println(F("Not provisioned: no Wi-Fi, no posting. send HELP on this console to see how"));
        sleepBeating(30000);
    }
    g_plain = (strncmp(g_creds->url, "http://", 7) == 0);

    // the first connect and the OTA check both happen here, so setup() never waits for them.
    pwBusyStart(&g_watch, millis());
    connectWiFi(g_creds->ssid, g_creds->pass);
    pwBusyEnd(&g_watch, millis());

#if OTA_ENABLED
    if (WiFi.status() == WL_CONNECTED) {
        // a download can take minutes, so the main loop stops supervising this task for it.
        pwPause(&g_watch, true, millis());
        checkAndApplyOTA();
        pwPause(&g_watch, false, millis());
    }
#endif

    Backoff backoff;
    backoffInit(&backoff);
    PostGate gate;
    pgInit(&gate);
    uint32_t downSinceMs   = 0;
    uint32_t lastDownLog   = 0;
    uint32_t posts         = 0;
    // the post task owns the clock. a TLS post waits for it and the main loop never asks for it
    bool needsClock = (strncmp(g_creds->url, "https://", 8) == 0);
    TimeGate clock;
    tgInit(&clock, millis());
    uint32_t lastClockLog = 0;

    for (;;) {
        uint32_t now = millis();
        pwBeat(&g_watch, now);

        // ask the gate on every pass, Wi-Fi up or not, so a back-off that has run its time clears
        // and is never left to age while the radio is down
        bool gateOpen = pgMayPost(&gate, now);
        bool up = (WiFi.status() == WL_CONNECTED);
        if (up) {
            // the signal goes in before the flag, so a reader that sees Wi-Fi up never reads a stale zero
            g_rssi = WiFi.RSSI();
            g_wifiUp = true;
            downSinceMs = 0;
        } else {
            g_wifiUp = false;
            if (downSinceMs == 0) downSinceMs = now ? now : 1;
            // the core reconnects on its own. after a minute without it, ask once more.
            if ((uint32_t)(now - downSinceMs) >= 60000UL) {
                pwBusyStart(&g_watch, now);
                reconnectWiFi();
                pwBusyEnd(&g_watch, millis());
                downSinceMs = millis() ? millis() : 1;
            }
            if (lastDownLog == 0 || (uint32_t)(now - lastDownLog) >= WIFI_DOWN_LOG_MS) {
                lastDownLog = now ? now : 1;
                Serial.println(F("Wi-Fi is down - bodies are replaced until it reconnects"));
            }
            sleepBeating(500);
            continue;
        }

        // the gate is closed only while a back-off is pending (see PostGate)
        if (!gateOpen) {
            sleepBeating(200);
            continue;
        }

        // the certificate dates are checked by the hub against the clock, so a TLS post waits until SNTP has set it.
        // while it has not, nothing is taken from the mailbox (newer bodies replace the old one),
        // the panel shows NET after POST_STALE_MS and the alarms and relays carry on
        if (needsClock) {
            TimeAction act = tgStep(&clock, now, (uint32_t)time(nullptr));
            if (act == TG_START) {
                configTime(0, 0, NTP_SERVER_1, NTP_SERVER_2, NTP_SERVER_3);
                Serial.println(F("Asking SNTP for the time. TLS posts wait for it"));
            } else if (act == TG_SYNCED) {
                Serial.println(F("The clock is set. TLS posts can start"));
            }
            if (!tgMayPostTls(&clock)) {
                if (lastClockLog == 0 || (uint32_t)(now - lastClockLog) >= 60000UL) {
                    lastClockLog = now ? now : 1;
                    Serial.println(F("The clock is not set yet, so no TLS post is tried"));
                }
                sleepBeating(500);
                continue;
            }
        }

        size_t len = 0;
        bool have = false;
        if (xSemaphoreTake(g_lock, pdMS_TO_TICKS(100)) == pdTRUE) {
            have = mbTake(&g_box, g_work, sizeof g_work, &len);
            xSemaphoreGive(g_lock);
        }
        if (!have) {
            sleepBeating(100);
            continue;
        }

        pwBusyStart(&g_watch, millis());
        HttpResult res = httpPost(String(g_creds->url), String(g_work), g_creds->key);
        pwBusyEnd(&g_watch, millis());
        int code = res.code;

        Serial.print(F("POST "));
        Serial.println(code);
        if (res.handshakeMs > 0 && (posts == 0 || posts % 60 == 0)) {
            Serial.print(F("TLS connect and handshake took "));
            Serial.print(res.handshakeMs);
            Serial.print(F(" ms, lowest free heap "));
            Serial.print((uint32_t)ESP.getMinFreeHeap());
            Serial.println(F(" bytes"));
        }
        uint32_t backoffWait = (code >= 200 && code < 300) ? 0 : backoffFailure(&backoff);
        PostOutcome out = poClassify(code, res.retryAfterSec, backoffWait);
        if (out.kind == PK_OK) {
            g_ok++;
            g_keyRejected = false;
            g_counterRejected = false;
            g_addressWrong = false;
            backoffSuccess(&backoff);
            pgSuccess(&gate);
        } else {
            g_failed++;
            g_keyRejected = (out.kind == PK_AUTH);
            g_counterRejected = (out.kind == PK_CONFLICT);
            g_addressWrong = (out.kind == PK_NOTFOUND);
            pgFailed(&gate, millis(), out.waitMs);
            Serial.print(F("Post failed ("));
            Serial.print(poKindName(out.kind));
            if (code >= 0) {
                Serial.print(F(", status "));
                Serial.print(code);
            }
            Serial.print(F(") - next attempt in "));
            Serial.print(out.waitMs / 1000);
            Serial.println(F(" s"));
            if (out.kind == PK_REDIRECT) {
                Serial.println(F("A redirect is not followed. check that the address is https:// and that the server does not redirect that path"));
            } else if (out.kind == PK_NOTFOUND) {
                Serial.println(F("The server answered 404: the address is wrong (check the path and that it does not end in a slash). retrying will not fix it, so the hub tries again once in ten minutes"));
            } else if (out.kind == PK_CONFLICT) {
                Serial.println(F("The server has seen a newer boot counter from this machine (status 409), so this hub's posts are refused. an admin has to accept a new counter in the dashboard (\"accept a new counter\"). the hub tries again once in ten minutes"));
            } else if (out.kind == PK_AUTH) {
                Serial.println(F("The key was rejected. retrying will not fix it, so the hub tries again once in ten minutes. check the key"));
            }
        }

        g_stackFree = uxTaskGetStackHighWaterMark(NULL);
        if (posts == 0 || posts % 60 == 0) {
            Serial.print(F("Post task stack: "));
            Serial.print((uint32_t)g_stackFree);
            Serial.print(F(" of "));
            Serial.print((uint32_t)POST_TASK_STACK_BYTES);
            Serial.println(F(" bytes still free at the lowest point"));
        }
        posts++;
    }
}

}  // namespace

void postTaskStart(const Credentials* creds) {
    g_creds = creds;
    mbInit(&g_box);
    pwInit(&g_watch, millis());
    g_lock = xSemaphoreCreateMutex();
    xTaskCreatePinnedToCore(postTask, "post", POST_TASK_STACK_BYTES, nullptr,
                            POST_TASK_PRIORITY, &g_task, POST_TASK_CORE);
}

bool postSubmit(const char* body, size_t len) {
    if (!g_lock) return false;
    // the holder keeps the lock only for a copy, so this wait is microseconds. it is bounded
    // anyway, because the main loop must never wait on the network side.
    if (xSemaphoreTake(g_lock, pdMS_TO_TICKS(20)) != pdTRUE) {
        g_dropped++;
        return false;
    }
    PutResult r = mbPut(&g_box, body, len);
    xSemaphoreGive(g_lock);
    return r != PUT_TOO_BIG;
}

bool postTaskHealthy(uint32_t nowMs) {
    return pwHealthy(&g_watch, nowMs, POST_BUSY_LIMIT_MS, POST_IDLE_LIMIT_MS);
}

bool postWifiRssi(int* rssi) {
    if (!g_wifiUp) return false;
    *rssi = (int)g_rssi;
    return true;
}

uint32_t postCountReplaced() {
    uint32_t n = g_dropped;
    if (g_lock && xSemaphoreTake(g_lock, pdMS_TO_TICKS(20)) == pdTRUE) {
        n += g_box.replaced;
        xSemaphoreGive(g_lock);
    }
    return n;
}

bool postKeyRejected() { return g_keyRejected; }
bool postPlainMode()   { return g_plain; }
bool postCounterRejected() { return g_counterRejected; }
bool postAddressWrong() { return g_addressWrong; }
uint32_t postCountFailed() { return g_failed; }
uint32_t postCountOk()     { return g_ok; }
uint32_t postStackHighWater() { return g_stackFree; }
