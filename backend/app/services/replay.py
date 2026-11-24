"""
Replay protection for ingest.

A node may send a pair in each post: `boot` (a count kept in its flash that rises at every restart) and `seq` (a count that
rises by one per post). The pair of the last post accepted is kept on the device. A post is judged against it, under the
device lock, so two posts racing cannot both pass:

  accept     the pair is newer than the last (boot first, then seq). Or the machine has not sent the pair before. The pair
             is stored
  duplicate  the exact pair last accepted, arriving again. It is a retry of a post whose answer was lost, so the reply is 200
             with a marker and nothing is stored. A node never loops on it
  old        an older pair. Refused with 409
  missing    a machine that has ever sent the pair now sends none or only half of it. Refused with 409, since dropping the
             pair is how a replay would get past the check

A machine that has never sent the pair (older firmware, the simulator, an API client) is accepted as before and shown as
having no replay protection.

What this does not stop: someone holding the key can still post pairs that are newer than the last. That is what hashed keys,
TLS and key rotation are for. It does stop a captured post being sent again and a post from before the last one.
"""

from __future__ import annotations

ACCEPT, DUPLICATE, OLD, MISSING, CEILING = "accept", "duplicate", "old", "missing", "ceiling"

# no real node reaches these, so a post at or past them is refused outright. Without the bound one post with the largest values
# would make every real post "older" and lock the machine out (anyone who has ever held the key could do it).
# boot: the schema allows 2,147,483,647. A flash counter rises once per restart and would need two thousand million of them;
# a Pico that falls back to Unix seconds as its boot is at about 1,800 million today and passes this bound in 2036
# (Unix time 2,100,000,000), which is ten years of room. Revisit it then.
# seq: the schema allows 4,294,967,295. It rises by one per post and a machine may post once a second at most (the rate limit is 60 a
# minute), so 4,000,000,000 is over 126 years of posting
BOOT_CEILING = 2_100_000_000
SEQ_CEILING = 4_000_000_000
# a rise in boot of more than this in one post (or in seq within one boot) is accepted but recorded and shown as a warning. A
# restart adds one (a few when the node boots without Wi-Fi). A seq that jumps by a million is not lost posts. The Pico's one move
# from a small counter to Unix seconds is a legitimate jump and shows once
BOOT_JUMP_WARN = 1_000
SEQ_JUMP_WARN = 1_000_000

REFUSAL_TEXT = {
    CEILING: (
        "this boot or seq is higher than any machine could reach, so it was refused. "
        "If it came from the machine itself its counter is damaged"
    ),
    OLD: (
        "this post's boot and seq are older than the last one accepted for this machine. "
        "If its flash was wiped an admin can accept a new counter"
    ),
    MISSING: "this machine always sends boot and seq and this post did not carry both",
}


def judge(device, boot: int | None, seq: int | None) -> str:
    if (boot is not None and boot > BOOT_CEILING) or (seq is not None and seq > SEQ_CEILING):
        return CEILING
    has_pair = boot is not None and seq is not None
    if not has_pair:
        return MISSING if device.replay_protected else ACCEPT
    if not device.replay_protected or device.last_boot is None or device.last_seq is None:
        return ACCEPT
    last = (device.last_boot, device.last_seq)
    pair = (boot, seq)
    if pair == last:
        return DUPLICATE
    return ACCEPT if pair > last else OLD


def jump_note(last_boot, last_seq, boot: int, seq: int) -> str | None:
    """A sentence when the pair rose by more than a restart or lost posts can explain. None otherwise."""
    if last_boot is None or last_seq is None:
        return None
    if boot - last_boot > BOOT_JUMP_WARN:
        return f"boot jumped from {last_boot} to {boot} in one post"
    if boot == last_boot and seq - last_seq > SEQ_JUMP_WARN:
        return f"seq jumped from {last_seq} to {seq} in one post"
    return None


def record_accept(device, boot: int | None, seq: int | None, now=None) -> None:
    if boot is None or seq is None:
        return
    note = jump_note(device.last_boot, device.last_seq, boot, seq) if device.replay_protected else None
    if note:
        device.counter_jump_at = now
        device.counter_jump_note = note
    device.replay_protected = True
    device.last_boot = boot
    device.last_seq = seq
    if device.replay_refused:
        device.replay_refused = 0
        device.replay_refused_at = None


def record_refusal(device, now) -> None:
    device.replay_refused = (device.replay_refused or 0) + 1
    device.replay_refused_at = now
