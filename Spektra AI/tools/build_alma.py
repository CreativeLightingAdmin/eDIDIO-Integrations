"""Generate a 2-controller .spektra from the CEC Level 8 functionality statement.

Design generated from the functionality statement (not a copy of the as-built),
using the occupancy pattern reverse-engineered from the real project:

  occupancy sensor = a physical INPUT whose short action starts a timed LIST;
  the LIST does [ARC full -> wait occupied-time -> MIN -> wait off-delay -> OFF];
  re-detection restarts the list (occupancy hold); the active PROFILE selects the
  office-hours vs after-hours list (same input -> different list per profile).

Two controllers (MACs supplied):
  #2 "Open Areas"  (2 DALI lines): open-plan/corridor/kitchen occupancy + corridor
                    logic + Type-4 open-plan toggle (after-hours only) + profile-switch
                    schedules/lists.
  #1 "Meeting Rooms" (1 DALI line): meeting rooms with Type-2 panels + occupancy timeout.

DALI group addressing and line assignment are the design's own convention (group N ->
target 64+N, line L -> linemask 1<<(L-1)); real short/group addresses come from the DALI
layout drawing / commissioning. Run: py -3 tools/build_alma.py
"""
import copy
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Two controllers (from the as-built, used here as the example project's MACs).
MAC_MAIN = "40:D8:55:1B:A5:90"   # #2 "Open Areas" — 2 DALI lines, sensors+lists+logic
MAC_ROOMS = "40:D8:55:1B:A5:8F"  # #1 "Meeting Rooms" — 1 DALI line, panels

# TriggerType values
DALI_ARC, DALI_COMMAND, LIST_START, PROFILE_CHANGE, NO_COMMAND = 0, 1, 9, 30, 254
# DALICommandType values (used as 'value' of a DALI_COMMAND)
CMD_OFF, CMD_FADE_UP, CMD_FADE_DOWN, CMD_MAX, CMD_MIN = 0, 1, 2, 5, 6
GROUP_BASE = 64                  # group N -> DALI target 64+N (eDIDIO convention)
OFFICE, AFTER = 0, 1
MIN = 60                         # seconds per minute

MOMENTARY = 0   # TriggerOperationType.MOMENTARY (EdidioInput.type for a push button)

def line_mask(line):
    return 1 << (line - 1)

def cmd(commandtype=NO_COMMAND, zone=0, linemask=0, target=0, value=0, query=0):
    return {"commandtype": commandtype, "zone": zone, "linemask": linemask,
            "target": target, "value": value, "query": query}

def _dur_unit(seconds):
    if seconds and seconds % 3600 == 0:
        return seconds // 3600, "Hours"
    if seconds and seconds % 60 == 0:
        return seconds // 60, "Minutes"
    return seconds, "Seconds"

def step(index, seconds, action):
    """A list step with the UI-display fields (index/duration/timeUnit) the app needs."""
    dur, unit = _dur_unit(seconds)
    return {"index": index, "action": action, "duration": dur, "timeUnit": unit,
            "time_until_next": seconds}


def occupancy_list(index, name, group, line, occupied_min, off_min):
    """3-step occupancy list: full -> (wait occupied) -> min -> (wait off) -> off.
    Re-triggering the list restarts step 0, holding the area lit while occupied."""
    g, lm = GROUP_BASE + group, line_mask(line)
    return {
        "name": name, "index": index, "loop_on_startup": False, "state": 0,
        "isShow": False, "scheduledDates": [], "totalStepCount": 3,
        "steps": [
            step(0, occupied_min * MIN, cmd(DALI_ARC, target=g, value=254, linemask=lm)),
            step(1, off_min * MIN, cmd(DALI_COMMAND, target=g, value=CMD_MIN, linemask=lm)),
            step(2, 0, cmd(DALI_ARC, target=g, value=0, linemask=lm)),
        ],
        "error": None,
    }


def profile_switch_list(index, name, profile):
    return {"name": name, "index": index, "loop_on_startup": False, "state": 0,
            "isShow": False, "scheduledDates": [], "totalStepCount": 1,
            "steps": [step(0, 0, cmd(PROFILE_CHANGE, value=profile))],
            "error": None}


def schedule(index, name, time_str, target_list):
    return {"name": name, "index": index, "IsEnabled": True, "repeat": 1,
            "monthsMask": 4095, "weekdaysMask": 31, "yearly": True,
            "startEvent": {"command": cmd(LIST_START, zone=255, target=target_list, value=2),
                           "type": 0, "date": "2025-01-01", "time": time_str, "offsetBefore": True},
            "endEvent": {"command": cmd(), "type": 0, "date": "2000-00-00",
                         "time": "00:00:00", "offsetBefore": False},
            "endEventIsActive": False, "error": None}


def sensor_input(index, name, list_index):
    """An occupancy sensor wired to a physical input: short action starts its list."""
    return {"name": name, "index": index, "type": MOMENTARY,
            "shortLowAction": cmd(LIST_START, target=list_index, value=0),
            "longHighAction": cmd(), "error": None}


def type2_pair(index, name, group, line):
    """Type-2 panel: top = on / long fade-up; bottom = off / long fade-down."""
    g, lm = GROUP_BASE + group, line_mask(line)
    return [
        {"name": f"{name} On/Up", "index": index, "type": MOMENTARY,
         "shortLowAction": cmd(DALI_COMMAND, target=g, value=CMD_MAX, linemask=lm),
         "longHighAction": cmd(DALI_COMMAND, target=g, value=CMD_FADE_UP, linemask=lm), "error": None},
        {"name": f"{name} Off/Down", "index": index + 1, "type": MOMENTARY,
         "shortLowAction": cmd(DALI_COMMAND, target=g, value=CMD_OFF, linemask=lm),
         "longHighAction": cmd(DALI_COMMAND, target=g, value=CMD_FADE_DOWN, linemask=lm), "error": None},
    ]


def type4_toggle(index, zone_group, line, active):
    """Type-4 open-plan toggle. Active only in the after-hours profile (NO_COMMAND in
    office -> panel ignored during office hours, per the functionality statement)."""
    action = cmd(DALI_COMMAND, target=GROUP_BASE + zone_group, value=CMD_MAX,
                 linemask=line_mask(line)) if active else cmd()
    return {"name": f"Open-Plan Toggle Z{zone_group + 1}", "index": index,
            "type": MOMENTARY, "shortLowAction": action,
            "longHighAction": cmd(), "error": None}


def blank_input(index):
    return {"name": f"Input {index + 1}", "index": index, "type": MOMENTARY,
            "shortLowAction": cmd(), "longHighAction": cmd(), "error": None}


def template_edidio():
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "edidio_spektra_ai", "templates",
                       "controller_template.spektratpl.spektra")
    with open(tpl, encoding="utf-8") as fh:
        return json.load(fh)["data"]


# Fixed-slot sections must always contain their full count of slots (configured +
# disabled blanks) or SpektraPlus shows a short list. These counts come from the
# controller template / supportedFeatures.
SLOT_COUNTS = {"schedules": 9, "lists": 32, "logicActions": 5, "burnIns": 2}


def _blanks_from_template():
    """Clone proper DISABLED blank slots from the template (a non-first slot is a
    real blank; slot 0/1 hold template example content)."""
    t = template_edidio()
    return {
        "schedules": t["schedules"][2], "lists": t["lists"][2],
        "logicActions": t["logicActions"][1], "burnIns": t["burnIns"][1],
        "outputs": t["profiles"][0]["outputs"],   # 4 default output slots
    }


_BLANKS = _blanks_from_template()
_LABELS = {"schedules": "Schedule", "lists": "List", "logicActions": "Logic",
           "burnIns": "Burn In"}


def _blank(section, index):
    b = copy.deepcopy(_BLANKS[section])
    b["index"] = index
    if "name" in b:
        b["name"] = f"{_LABELS[section]} {index + 1}"
    return b


def pad_slots(section, entries):
    """Return a full-length array: configured entries at their indices, template
    disabled-blanks everywhere else."""
    by_index = {e["index"]: e for e in entries}
    return [by_index.get(i, _blank(section, i)) for i in range(SLOT_COUNTS[section])]


def default_outputs():
    return copy.deepcopy(_BLANKS["outputs"])


# --- occupancy areas on the MAIN controller (from the functionality statement) ---
# (group, line, name, OH occupied/off min, AH occupied/off min)
MAIN_AREAS = [
    (0, 1, "General Open-Plan", (30, 2), (20, 1)),
    (1, 1, "Corridor",          (40, 2), (30, 2)),
    (2, 1, "Kitchen",           (10, 2), (5, 1)),
]
# Meeting rooms on the ROOMS controller (occupancy timeout uses the 'general' timing).
ROOM_AREAS = [
    (0, 1, "Meeting Room 1", (30, 2), (20, 1)),
    (1, 1, "Meeting Room 2", (30, 2), (20, 1)),
]


def build_main():
    ed = template_edidio()
    lists, sensor_list_map = [], []      # sensor_list_map[i] = (oh_index, ah_index)
    li = 0
    for group, line, name, oh, ah in MAIN_AREAS:
        lists.append(occupancy_list(li, f"{name} OH", group, line, oh[0], oh[1]))
        lists.append(occupancy_list(li + 1, f"{name} AH", group, line, ah[0], ah[1]))
        sensor_list_map.append((li, li + 1))
        li += 2
    office_list, after_list = li, li + 1
    lists.append(profile_switch_list(office_list, "Office Hours", OFFICE))
    lists.append(profile_switch_list(after_list, "After Hours", AFTER))

    def profile(pidx):
        inputs = []
        # occupancy sensor inputs -> OH list in office profile, AH list in after-hours
        for si, (group, line, name, _oh, _ah) in enumerate(MAIN_AREAS):
            oh_i, ah_i = sensor_list_map[si]
            inputs.append(sensor_input(si, f"{name} Sensor",
                                       oh_i if pidx == OFFICE else ah_i))
        # Type-4 open-plan toggles (zones 1-4) — active only after-hours
        base = len(inputs)
        for z in range(4):
            inputs.append(type4_toggle(base + z, zone_group=z, line=1,
                                       active=(pidx == AFTER)))
        while len(inputs) < 12:
            inputs.append(blank_input(len(inputs)))
        return {"inputs": inputs, "outputs": default_outputs(), "sensors": [],
                "daliInputs": [], "irs": [], "userLevels": []}

    corridor_logic = {
        "name": "Corridor follows occupancy", "index": 0,
        "comparisonObject": cmd(DALI_COMMAND, target=GROUP_BASE + 0, value=0),
        "comparisonType": 1, "comparisonValue": 1, "isEnabled": True,
        "trueAction": cmd(DALI_ARC, target=GROUP_BASE + 1, value=254, linemask=1),
        "falseAction": cmd(), "error": None}

    ed.update({
        "firmwareVersion": "1.5.7", "lineTypes": [1, 1, 0, 0],  # 2 DALI lines
        "sequences": [], "themes": [], "zones": [], "translations": [],
        "schedules": pad_slots("schedules", [
            schedule(0, "Office Hours", "07:00:00", office_list),
            schedule(1, "After Hours", "18:00:00", after_list)]),
        "logicActions": pad_slots("logicActions", [corridor_logic]),
        "burnIns": pad_slots("burnIns", []),
        "lists": pad_slots("lists", lists),
        "profiles": [profile(OFFICE), profile(AFTER)],
        "error": "",
    })
    return ed


def build_rooms():
    ed = template_edidio()
    lists, room_list_map = [], []
    li = 0
    for group, line, name, oh, ah in ROOM_AREAS:
        lists.append(occupancy_list(li, f"{name} OH", group, line, oh[0], oh[1]))
        lists.append(occupancy_list(li + 1, f"{name} AH", group, line, ah[0], ah[1]))
        room_list_map.append((li, li + 1))
        li += 2
    # Each controller runs its own schedule/profile engine, so this controller needs
    # its own profile-switch lists + schedules (else it never leaves its boot profile).
    office_list, after_list = li, li + 1
    lists.append(profile_switch_list(office_list, "Office Hours", OFFICE))
    lists.append(profile_switch_list(after_list, "After Hours", AFTER))

    def profile(pidx):
        inputs = []
        for ri, (group, line, name, _oh, _ah) in enumerate(ROOM_AREAS):
            # Type-2 panel (2 buttons) to turn the room on/off + fade
            inputs += type2_pair(len(inputs), name, group, line)
            # room occupancy sensor -> times the room out (OH/AH per profile)
            oh_i, ah_i = room_list_map[ri]
            inputs.append(sensor_input(len(inputs), f"{name} Sensor",
                                       oh_i if pidx == OFFICE else ah_i))
        while len(inputs) < 12:
            inputs.append(blank_input(len(inputs)))
        return {"inputs": inputs, "outputs": default_outputs(), "sensors": [],
                "daliInputs": [], "irs": [], "userLevels": []}

    ed.update({
        "firmwareVersion": "1.5.7", "lineTypes": [1, 0],  # 1 DALI line
        "sequences": [], "themes": [], "zones": [], "translations": [],
        "schedules": pad_slots("schedules", [
            schedule(0, "Office Hours", "07:00:00", office_list),
            schedule(1, "After Hours", "18:00:00", after_list)]),
        "logicActions": pad_slots("logicActions", []),
        "burnIns": pad_slots("burnIns", []),
        "lists": pad_slots("lists", lists),
        "profiles": [profile(OFFICE), profile(AFTER)],
        "error": "",
    })
    return ed


def set_identity(edidio, mac, device_name, project_uid, project_name):
    """Give a controller its own identity so SpektraPlus can list/select it. The app
    resolves controllers by network.mac, so it MUST match the edidios key. Network is
    otherwise placeholder for an offline (never-connected) generated project."""
    net = edidio.setdefault("network", {})
    net.update({"mac": mac, "deviceName": device_name, "ip": "", "staticIp": "",
                "isConnected": False})
    edidio["project_uid"] = project_uid
    edidio["project_name"] = project_name
    edidio["projectName"] = f"{project_uid}${project_name}"
    return edidio


def build():
    now = int(time.time() * 1000)
    uid = str(now)
    name = "CEC Building Level 8"
    main = set_identity(build_main(), MAC_MAIN, "CEC L8 Open Areas", uid, name)
    rooms = set_identity(build_rooms(), MAC_ROOMS, "CEC L8 Meeting Rooms", uid, name)
    return {
        "fileFormatVersion": 3, "appVersion": "spektra-ai-build",
        "name": "CEC Building Level 8 (generated from functionality statement)",
        "uid": str(now), "createdAt": now, "updatedAt": now, "lastOpenedAt": now,
        "notes": ("Generated by Spektra AI from 'CEC building level 8 Functionality "
                  "Statement rev3'. Occupancy = low-level sensors on INPUTS that start "
                  "timed LISTS (fade-to-min then off); the active PROFILE selects office "
                  "vs after-hours timing. DALI group/line addressing is the design's "
                  "convention (group N -> target 64+N); real addresses come from the "
                  "DALI layout drawing / commissioning."),
        "colourPalette": [], "widgetPages": [],
        "targetZoneIndex": None, "targetEdidioMac": MAC_MAIN,
        "daliCommissioningPreferences": {
            "selectionVolume": 0.3, "turnOffWithdrawnDevices": False,
            "blockSelectionChangesInLivePreview": True, "livePreviewUsesMaxAndOff": True},
        "syncData": {"syncStates": {}, "rollbackHistory": [], "syncQueue": []},
        "edidios": {MAC_MAIN: main, MAC_ROOMS: rooms},
    }


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else r"C:/Users/Mike/Desktop/temp/CEC_L8_generated.spektra"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(build(), fh, indent=2)
    print("wrote", out)
