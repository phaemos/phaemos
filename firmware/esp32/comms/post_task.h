// post_task.h - the network side of the hub. the main loop never waits on the network. it
// builds a body every reading interval and hands it to this task through a one-slot mailbox
// that always holds the newest body. this task owns the Wi-Fi connect, the reconnects, the OTA
// check and every HTTP post.
//
// what the two tasks share and how it is shared:
//   the mailbox         one mutex, held only for a copy of the body
//   Wi-Fi state         the post task writes the connected flag and the signal strength into
//                       atomics and the main loop reads them. the main loop never calls the
//                       Wi-Fi API
//   the post counters   atomics written by the post task
//   the watch           atomics (see post_queue.h). the main loop feeds its watchdog only while
//                       the post task is healthy
#pragma once

#include <Arduino.h>

// creates the mutex and starts the task. call it once, from the hub core's boot, before any sensor set-up.
// creds must outlive the task. with nothing stored the task never touches the radio and posts nothing.
struct Credentials;
void postTaskStart(const Credentials* creds);

// hands the newest body to the post task. never blocks for more than a moment: a body that
// finds the slot full replaces the older one, which is counted. returns false when the body is
// too large or the slot was busy, in which case it was dropped and counted.
bool postSubmit(const char* body, size_t len);

// true while the post task is healthy. the main loop feeds the watchdog only while this holds.
bool postTaskHealthy(uint32_t nowMs);

// the latest Wi-Fi state, as the post task saw it. returns false when Wi-Fi is down.
bool postWifiRssi(int* rssi);

// a 401 or 403 came back and no post has succeeded since: the key is wrong. the panel shows NET.
bool postKeyRejected();
// the hub posts over plain HTTP (a bench build only). the panel shows PLN and the post says so.
bool postPlainMode();
// the backend answered 409 and no post has succeeded since: it holds a newer boot counter for this
// machine and an admin has to accept a new counter (dashboard, "accept a new counter")
bool postCounterRejected();
// the backend answered 404: the address is wrong. the panel shows NET at once.
bool postAddressWrong();

uint32_t postCountReplaced();
uint32_t postCountFailed();
uint32_t postCountOk();
// the post task's stack high-water mark in bytes (the least free stack seen so far).
uint32_t postStackHighWater();
