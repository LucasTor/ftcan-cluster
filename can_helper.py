#!/usr/bin/env python3
"""FTCAN 2.0 tagged real-time broadcast reader.

FuelTech devices broadcast measurements on the "real-time reading broadcast"
messages (MessageID 0x_FF — i.e. the CAN frame's low byte is 0xFF). Each
measurement is a MeasureID(2 bytes) + Value(2 bytes) pair, big-endian, where
MeasureID = (DataID << 1) | status_bit. Frames come in three layouts:

  * Standard CAN (DataFieldID 0): the data field is just MeasureID/Value pairs.
  * FTCAN single packet (DataFieldID 2/3, first byte 0xFF): pairs after the 0xFF.
  * FTCAN segmented (first byte = segment index): segment 0 carries a 2-byte
    total length then the payload start; following segments append; reassembled
    into MeasureID/Value pairs.

We listen to every device on the bus (ECU + wideband, etc.) and map the DataIDs
we care about into SensorState. (See decode_dump.py to inventory a capture, and
log_realtime() below to discover still-unmapped signals like the fan output.)
"""

import can
import time

from model import SensorState

# Numeric measurements: DataID -> (SensorState field, multiplier).
# Validated against dump.txt and the FTCAN 2.0 measure table. 16-bit values are
# read as signed (two's complement) so temps / MAP can go negative.
MEASURE_MAP = {
    0x0001: ("tps", 0.1),
    0x0002: ("map", 0.001),                 # bar (signed: vacuum is negative)
    0x0003: ("air_temp", 0.1),
    0x0004: ("engine_temp", 0.1),
    0x0005: ("oil_pressure_bar", 0.001),
    0x0006: ("fuel_pressure_bar", 0.001),
    0x0007: ("water_pressure_bar", 0.001),
    0x0009: ("battery", 0.01),              # volts (12.06 V from the dump)
    0x000C: ("wheel_speed_fl_kmh", 1),
    0x000D: ("wheel_speed_fr_kmh", 1),
    0x000E: ("wheel_speed_rl_kmh", 1),
    0x000F: ("wheel_speed_rr_kmh", 1),
    0x0027: ("lambda_afr", 0.001),          # general Exhaust O2 (from the wideband)
    0x0042: ("rpm", 1),
    0x008C: ("oil_temp", 0.1),
    # Flex-fuel ethanol content (%). "Fuel Ethanol Percentage", DataID 0x021C,
    # broadcast by the ECU at 10Hz. Added late to FTCAN 2.0 (protocol revision 043,
    # 2026-07-06 — absent from the older Protocol_FTCAN20.pdf whose table ends at
    # 0x024C), which is why earlier captures/dumps couldn't surface it.
    0x021C: ("ethanol", 0.1),
    0x0281: ("fuel_level", 0.1),            # % (our ESP32 sender; unit TBD in the spec)
}

# DataID -> required sender ProductTypeID (arbitration_id >> 19). The spec also lists
# 0x0281 "Fuel Level" as a PowerFT ECU measure, so without this gate the ECU's own
# (unconnected) fuel reading would fight our ESP32's. 0x03F8 = ProductID 0x7F00..0x7F1F,
# top of the low-priority range, where our fuel-level sender lives.
SOURCE_GATE = {
    0x0281: 0x03F8,
}

# Status / special DataIDs handled below in _apply().
DATAID_GEAR = 0x0011        # signed gear (Note 2)
DATAID_LAUNCH = 0x0008      # ECU launch mode (2-step / 3-step / burnout): nonzero = armed
DATAID_FAN = 0x004D         # ECU Eletro Fan (Note 7: 0 = off, 1 = on)
DATAID_DAYNIGHT = 0x0153    # "Day/Night state" (Note 12: 0 = day, 1 = night).
                            # NOT 0x007D — that's the day/night *button* state
                            # and is "Internal use only" (never broadcast);
                            # 0x0153 verified live on the car 2026-07-30.

GEAR_LABEL = {-2: "P", -1: "R", 0: "N", 1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6"}


def _signed(v):
    return v - 65536 if v >= 32768 else v


def _pairs(payload, out):
    """Append (measure_id, raw_value) for each 4-byte pair in the payload."""
    for i in range(0, len(payload) - 3, 4):
        mid = (payload[i] << 8) | payload[i + 1]
        val = (payload[i + 2] << 8) | payload[i + 3]
        if mid:
            out.append((mid, val))


def _decode(cid, data, seg):
    """Decode one frame into a list of (measure_id, raw_value), reassembling
    segmented FTCAN packets via the per-id `seg` buffer."""
    out = []
    if not data:
        return out
    data_field_id = (cid >> 11) & 0x7
    if data_field_id == 0x00:                  # standard CAN
        _pairs(bytes(data), out)
    else:                                       # FTCAN (0x02 / 0x03 bridge)
        b0 = data[0]
        if b0 == 0xFF:                          # single packet
            _pairs(bytes(data[1:]), out)
        elif b0 == 0x00:                        # segment 0: total length + payload start
            total = (data[1] << 8) | data[2]
            seg[cid] = [total, bytearray(data[3:])]
        elif cid in seg:                        # continuation segment
            seg[cid][1] += bytes(data[1:])
            total, buf = seg[cid]
            if len(buf) >= total:
                _pairs(bytes(buf[:total]), out)
                del seg[cid]
    return out


def _apply(state, measures, product_type=None):
    """Map decoded measures into a SensorState update (stamps the CAN clock)."""
    updates = {}
    for mid, raw in measures:
        did = mid >> 1
        val = _signed(raw)
        if did in SOURCE_GATE and product_type != SOURCE_GATE[did]:
            continue
        if did in MEASURE_MAP:
            field, scale = MEASURE_MAP[did]
            updates[field] = val * scale
        elif did == DATAID_GEAR:
            updates["gear"] = val
            updates["gear_label"] = GEAR_LABEL.get(val, str(val))
        elif did == DATAID_LAUNCH:
            updates["two_step"] = (val != 0)
        elif did == DATAID_FAN:
            updates["radiator_fan"] = (val != 0)
        elif did == DATAID_DAYNIGHT:
            updates["night"] = (val == 1)
    if updates:
        state.update(updates)


# EGT-4 module simplified broadcast (read-only): the EGT-4 CAN module (e.g. our ESP32,
# or a real FuelTech unit) broadcasts 4 channels here — int16 big-endian, 0.125 C/bit
# at bytes 0-1/2-3/4-5/6-7. See EGT_README.md. We read it straight off the bus to show
# per-cylinder EGT on the dash, independent of whether the ECU re-broadcasts it.
EGT4_ID = 0x02400000        # FuelTech EGT-4 model A
EGT4_SCALE = 0.125          # degC per bit


def _decode_egt4(data):
    """Decode the EGT-4 simplified packet into {egt1..egt4} (°C)."""
    if len(data) < 8:
        return {}
    out = {}
    for i in range(4):
        raw = (data[i * 2] << 8) | data[i * 2 + 1]
        out[f"egt{i + 1}"] = _signed(raw) * EGT4_SCALE
    return out


def read_can(interface="socketcan", channel="can0", state=None):
    if state is None:
        state = SensorState()
    print("Starting FTCAN 2.0 tagged-broadcast listener on", channel, flush=True)

    # Real-time broadcast frames have a low byte of 0xFF (any FuelTech device); plus
    # the EGT-4 module's simplified packet (a fixed extended ID).
    filters = [
        {"can_id": 0x000000FF, "can_mask": 0x000000FF, "extended": True},
        {"can_id": EGT4_ID, "can_mask": 0x1FFFFFFF, "extended": True},
    ]
    bus = can.Bus(interface=interface, channel=channel,
                  receive_own_messages=False, can_filters=filters)
    seg = {}
    try:
        while True:
            msg = bus.recv(timeout=1.0)
            if msg is None:
                continue
            if not msg.is_extended_id:
                continue
            if msg.arbitration_id == EGT4_ID:
                state.update(_decode_egt4(msg.data))
                continue
            _apply(state, _decode(msg.arbitration_id, msg.data, seg),
                   product_type=msg.arbitration_id >> 19)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        bus.shutdown()


# --- Discovery logger: dump unmapped real-time measures (find fan, day/night) ---
RT_NAMES = {did: f[0] for did, f in MEASURE_MAP.items()}
RT_NAMES.update({DATAID_GEAR: "gear", DATAID_LAUNCH: "launch/2step",
                 DATAID_FAN: "radiator_fan", DATAID_DAYNIGHT: "day/night"})


def log_realtime(interface="socketcan", channel="can0"):
    """Log real-time broadcast measures on change (tag: [canrt]) for discovery."""
    filters = [{"can_id": 0x000000FF, "can_mask": 0x000000FF, "extended": True}]
    try:
        bus = can.Bus(interface=interface, channel=channel,
                      receive_own_messages=False, can_filters=filters)
    except Exception as e:
        print("[canrt] could not open bus:", e, flush=True)
        return
    print("[canrt] real-time broadcast logger on", channel, flush=True)
    seg, last = {}, {}
    try:
        while True:
            msg = bus.recv(timeout=1.0)
            if msg is None:
                continue
            product_id = msg.arbitration_id >> 14
            for mid, raw in _decode(msg.arbitration_id, msg.data, seg):
                did = mid >> 1
                now = time.monotonic()
                prev = last.get((product_id, did))
                if prev and prev[0] == raw and now - prev[1] < 1.5:
                    continue
                last[(product_id, did)] = (raw, now)
                name = RT_NAMES.get(did, "")
                print(f"[canrt] ProductID=0x{product_id:04X} DataID=0x{did:04X} {name}"
                      f" = {_signed(raw)} (0x{raw:04X})", flush=True)
    except Exception as e:
        print("[canrt] error:", e, flush=True)
    finally:
        bus.shutdown()
