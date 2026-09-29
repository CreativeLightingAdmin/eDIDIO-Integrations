// Builders that turn high-level lighting intents into framed eDIDIO protobuf
// messages ready to write to the TCP socket.
//
// Wire format: every message is prefixed with a 3-byte header:
//   [0xCD, lengthHigh, lengthLow]  followed by the serialized EdidioMessage.

const messages = require('./eDS10_ProtocolBuffer_pb.js');

const { CustomDALICommandType, DALICommandType, SpektraTargetType, SpektraActionType } = messages;

// DALI addressing: 0-63 individual, 64-79 group (address = 64 + group), 80
// broadcast. Scenes use the standard DALI "GO TO SCENE X" command (0x10 + scene)
// sent to the target address.
const DALI_GROUP_ADDRESS_BASE = 64;
const DALI_BROADCAST_ADDRESS = 80;
const DALI_GO_TO_SCENE_BASE = 0x10;

// Frame a serialized EdidioMessage with the 0xCD length-prefixed header.
function frame(edidioMessage) {
	const payload = edidioMessage.serializeBinary();
	const out = new Uint8Array(payload.length + 3);
	out.set([0xcd, (payload.length >> 8) & 0xff, payload.length & 0xff]);
	out.set(payload, 3);
	return out;
}

function wrapDali(configure) {
	const dali = new messages.DALIMessage();
	configure(dali);
	const edidio = new messages.EdidioMessage();
	edidio.setDaliMessage(dali);
	return frame(edidio);
}

// Send a raw DALI arc level (0-254) to a short address on a given line.
function daliArcLevel({ address, level, lineMask = 0b0001 }) {
	return wrapDali((dali) => {
		dali.setLineMask(lineMask);
		dali.setCustomCommand(CustomDALICommandType.DALI_ARC_LEVEL);
		dali.setAddress(address);
		dali.setArg(level);
	});
}

// Send an arc level to a whole DALI group, addressed as DALI_ARC_LEVEL to the
// group address (64 + group).
function daliGroupArcLevel({ group, level, lineMask = 0b0001 }) {
	return wrapDali((dali) => {
		dali.setLineMask(lineMask);
		dali.setCustomCommand(CustomDALICommandType.DALI_ARC_LEVEL);
		dali.setAddress(DALI_GROUP_ADDRESS_BASE + group);
		dali.setArg(level);
	});
}

// Send a standard DALI command (OFF, MAX_LEVEL, FADE_UP, RECALL_SCENE_X, ...).
function daliCommand({ address, command, arg = 0, lineMask = 0b0001 }) {
	return wrapDali((dali) => {
		dali.setLineMask(lineMask);
		dali.setCommand(command);
		dali.setAddress(address);
		if (arg) dali.setArg(arg);
	});
}

// Recall a stored DALI scene across all addresses on a line (broadcast). Encoded
// as the raw DALI "GO TO SCENE X" command (0x10 + scene) to broadcast address 80.
function daliBroadcastScene({ scene, lineMask = 0b0001 }) {
	return wrapDali((dali) => {
		dali.setLineMask(lineMask);
		dali.setAddress(DALI_BROADCAST_ADDRESS);
		dali.setCommand(DALI_GO_TO_SCENE_BASE + scene);
	});
}

// Recall a stored scene on a specific DALI group. Encoded as the raw DALI
// "GO TO SCENE X" command (0x10 + scene) to the group address (64 + group).
function daliSceneOnGroup({ group, scene, lineMask = 0b0001 }) {
	return wrapDali((dali) => {
		dali.setLineMask(lineMask);
		dali.setAddress(DALI_GROUP_ADDRESS_BASE + group);
		dali.setCommand(DALI_GO_TO_SCENE_BASE + scene);
	});
}

// Set DMX channel levels on a line.
//
// DMX channels are 1-based: level[i] is written to channel (channel + i). `repeat`
// tiles the level pattern that many times from `channel`, so e.g. levels=[r,g,b]
// with repeat=170 paints a whole 512-channel universe of RGB fixtures one colour.
// zone 0xFF addresses all zones on the line.
function dmxColour({ zone = 0, levels, universeMask = 0b0001, channel = 1, repeat = 1, fadeTimeBy10ms = 0 }) {
	const dmx = new messages.DMXMessage();
	if (zone) dmx.setZone(zone);
	dmx.setUniverseMask(universeMask);
	if (channel) dmx.setChannel(channel);
	if (repeat) dmx.setRepeat(repeat);
	dmx.setLevelList(levels);
	if (fadeTimeBy10ms) dmx.setFadeTimeBy10ms(fadeTimeBy10ms);
	const edidio = new messages.EdidioMessage();
	edidio.setDmxMessage(dmx);
	return frame(edidio);
}

// Start/pause a SpektraPlus sequence, theme, or static scene on a zone.
function spektraControl({ type, zone = 0, index = 0, action }) {
	const control = new messages.SpektraControlMessage();
	control.setType(type);
	control.setZone(zone);
	control.setIndex(index);
	control.setAction(action);
	const edidio = new messages.EdidioMessage();
	edidio.setSpektraControl(control);
	return frame(edidio);
}

// Stop SpektraPlus playback on a zone. Unlike SpektraControl STOP (which just
// halts), the SPEKTRA_STOP_SEQ external trigger also turns the output off —
// matching how the SpektraPlus app stops playback.
function spektraStop({ zone = 0, lineMask = 0xff } = {}) {
	const trigger = new messages.TriggerMessage();
	trigger.setType(messages.TriggerType.SPEKTRA_STOP_SEQ);
	trigger.setZone(zone);
	trigger.setLineMask(lineMask);
	trigger.setTargetIndex(0);
	trigger.setValue(0);

	const external = new messages.ExternalTriggerMessage();
	external.setTrigger(trigger);
	const edidio = new messages.EdidioMessage();
	edidio.setExternalTrigger(external);
	return frame(edidio);
}

// Heartbeat / "Are You There" keep-alive frame.
const AYT_FRAME = new Uint8Array([0xff, 0xf6]);

module.exports = {
	frame,
	daliArcLevel,
	daliGroupArcLevel,
	daliCommand,
	daliBroadcastScene,
	daliSceneOnGroup,
	dmxColour,
	spektraControl,
	spektraStop,
	AYT_FRAME,
	// Re-export enums so commands don't reach into the generated file.
	DALICommandType,
	SpektraTargetType,
	SpektraActionType,
};
