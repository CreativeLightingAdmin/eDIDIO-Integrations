"""Sanitized in-memory .spektra fixtures for tests (fake MACs, no real data)."""

MAC1 = "AA:BB:CC:00:00:01"
MAC2 = "AA:BB:CC:00:00:02"


def _cmd(commandtype=254, zone=0, linemask=0, target=0, value=0, query=0):
    return {"commandtype": commandtype, "zone": zone, "linemask": linemask,
            "target": target, "value": value, "query": query}


def _edidio():
    return {
        "firmwareVersion": "1.0.86",
        "sequences": [{"name": "Seq1", "index": 0,
                       "colours": [{"channelValues": [255, 0, 0]},
                                   {"channelValues": [0, 255, 0]}]}],
        "themes": [{"name": "Theme1", "index": 0,
                    "colours": [{"channelValues": [0, 254, 0]}]}],
        "schedules": [{"name": "Office", "index": 0, "IsEnabled": True,
                       "startEvent": {"command": _cmd(commandtype=12, zone=1,
                                                      linemask=1, target=0)}}],
        "logicActions": [], "lists": [], "zones": [], "burnIns": [], "translations": [],
        "profiles": [{
            "inputs": [{"name": "In1", "index": 0, "isMomentaryOperation": True,
                        "shortLowAction": _cmd(commandtype=1, zone=255, linemask=1, target=16),
                        "longHighAction": _cmd(), "error": None}],
            "outputs": [], "sensors": [], "daliInputs": [], "irs": [], "userLevels": [],
        }],
    }


def make_legacy(macs=(MAC1,)) -> dict:
    """A legacy project: no fileFormatVersion, sync in controllerSynchronisationIssues."""
    return {
        "appVersion": "1.0.0", "name": "Fixture Legacy", "uid": "1000",
        "createdAt": 1, "updatedAt": 2, "lastOpenedAt": 3, "notes": "",
        "colourPalette": [],
        "widgetPages": [{"id": "w1", "name": "Page"}],  # unknown-ish field to preserve
        "controllerSynchronisationIssues": {
            "failedToUpdateProjectSettings": [], "failedToRemoveProjectSettings": [],
            "configFilesDiffer": [
                {"mac": macs[0], "key": "inputs",
                 "first_attempt": "2025-01-01T00:00:00.000Z",
                 "last_attempt": "2025-01-01T00:05:00.000Z", "status": "STAGED"}],
        },
        "edidios": {m: _edidio() for m in macs},
    }


def make_v3(macs=(MAC1,)) -> dict:
    """A current v3 project: fileFormatVersion + syncData.syncStates."""
    return {
        "fileFormatVersion": 3,
        "appVersion": "1.0.0", "name": "Fixture V3", "uid": "2000",
        "createdAt": 1, "updatedAt": 2, "lastOpenedAt": 3, "notes": "",
        "colourPalette": [], "widgetPages": [],
        "syncData": {
            "syncStates": {
                f"{macs[0]}:inputs": {
                    "deviceMac": macs[0], "dataType": "inputs", "status": "UNSYNCED",
                    "lastSyncedStateHash": None, "lastReadStateHash": None,
                    "lastSyncTimestamp": None, "lastReadTimestamp": None}},
            "rollbackHistory": "DEFLATE:deadbeef",  # opaque compressed blob
            "syncQueue": [],
        },
        "edidios": {m: _edidio() for m in macs},
    }


def make_bad() -> dict:
    """A project with deliberate violations for the validator."""
    p = make_legacy()
    ed = p["edidios"][MAC1]
    ed["sequences"] = [{
        "name": "X" * 40,                       # over-length title (warning)
        "index": 200,                            # > 143 (error)
        "colours": [{"channelValues": [300, 0, 0]}],  # 300 out of range (error)
    }]
    ed["profiles"][0]["inputs"][0]["shortLowAction"] = _cmd(commandtype=9999)  # bad type
    return p
