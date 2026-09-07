// Pure-JavaScript eDIDIO protocol frame encoder — zero dependencies.
//
// Produces byte-identical output to the edidio_control_py library (and the
// pure-Python encoder used by the Extron/AMX drivers), but with no npm packages
// and no protobuf runtime — so it runs inside RTI's constrained JavaScript DDK
// engine.
//
// Wire format: 0xCD + 2-byte big-endian length + a serialized EdidioMessage.
// Only the fields needed for lighting control are hand-encoded. Field numbers
// and zero-emission rules are validated byte-for-byte in test/frames.test.js.

(function (root) {
	'use strict';

	// EdidioMessage field numbers.
	var F_MESSAGE_ID = 1, F_DALI = 18, F_DMX = 20, F_EXTERNAL_TRIGGER = 21, F_SPEKTRA_CONTROL = 27;
	// DALIMessage.
	var D_LINE_MASK = 1, D_ADDRESS = 2, D_COMMAND = 5, D_CUSTOM_COMMAND = 6, D_ARG = 9;
	// DMXMessage.
	var X_ZONE = 1, X_UNIVERSE_MASK = 2, X_CHANNEL = 3, X_REPEAT = 4, X_LEVEL = 5, X_FADE = 6;
	// SpektraControlMessage.
	var S_TYPE = 1, S_ZONE = 2, S_INDEX = 3, S_ACTION = 4;
	// ExternalTrigger / Trigger.
	var E_TRIGGER = 1, T_TYPE = 1, T_ZONE = 2, T_LINE_MASK = 3;

	// Enums.
	var DALI_ARC_LEVEL = 0, DALI_GROUP_ARC_LEVEL = 2, DALI_BROADCAST_SCENE = 3, DALI_SCENE_ON_GROUP = 4;
	// DALI addressing: 0-63 individual, 64-79 group (address = 64 + group), 80
	// broadcast. Scenes use the standard DALI "GO TO SCENE X" command (0x10 + scene)
	// sent to the target address.
	var DALI_GROUP_ADDRESS_BASE = 64, DALI_BROADCAST_ADDRESS = 80, DALI_GO_TO_SCENE_BASE = 0x10;
	var DALI_OFF = 0, DALI_FADE_UP = 1, DALI_FADE_DOWN = 2, DALI_STEP_UP = 3, DALI_STEP_DOWN = 4,
		DALI_MAX_LEVEL = 5, DALI_MIN_LEVEL = 6, DALI_RECALL_LAST = 10, DALI_IDENTIFY = 37;
	var SPEKTRA_SEQUENCE = 1, SPEKTRA_THEME = 2, SPEKTRA_STATIC = 3;
	var SPEKTRA_START = 0, SPEKTRA_STOP = 1, SPEKTRA_PAUSE = 2, TRIGGER_SPEKTRA_STOP_SEQ = 13;
	var DALI_ARC_LEVEL_MAX = 254;

	var NAMED_COMMANDS = {
		off: DALI_OFF, on: DALI_MAX_LEVEL, max: DALI_MAX_LEVEL, min: DALI_MIN_LEVEL,
		fade_up: DALI_FADE_UP, fade_down: DALI_FADE_DOWN, step_up: DALI_STEP_UP,
		step_down: DALI_STEP_DOWN, recall_last: DALI_RECALL_LAST, identify: DALI_IDENTIFY
	};

	// --- low-level encoding (all functions return arrays of byte values) ---

	function varint(value) {
		var out = [];
		var v = value;
		while (v >= 128) {
			out.push((v & 0x7f) | 0x80);
			v = Math.floor(v / 128);
		}
		out.push(v & 0x7f);
		return out;
	}

	function tag(field, wireType) {
		return varint(field * 8 + wireType);
	}

	function uint(field, value, always) {
		if (value === 0 && !always) return [];
		return tag(field, 0).concat(varint(value));
	}

	function packed(field, values) {
		var body = [];
		for (var i = 0; i < values.length; i++) body = body.concat(varint(values[i]));
		return tag(field, 2).concat(varint(body.length)).concat(body);
	}

	function embed(field, body) {
		return tag(field, 2).concat(varint(body.length)).concat(body);
	}

	function frame(body) {
		var n = body.length;
		return [0xcd, (n >> 8) & 0xff, n & 0xff].concat(body);
	}

	function clamp(v, lo, hi) {
		v = v | 0;
		if (v < lo) return lo;
		if (v > hi) return hi;
		return v;
	}

	function toBytes(arr) {
		return (typeof Uint8Array !== 'undefined') ? Uint8Array.from(arr) : arr;
	}

	// --- message builders ---

	function dali(mid, lineMask, address, opts) {
		var body = uint(D_LINE_MASK, lineMask, false).concat(uint(D_ADDRESS, address, false));
		if (opts.command !== undefined && opts.command !== null) {
			body = body.concat(uint(D_COMMAND, opts.command, true));
		}
		if (opts.customCommand !== undefined && opts.customCommand !== null) {
			body = body.concat(uint(D_CUSTOM_COMMAND, opts.customCommand, true));
		}
		if (opts.arg !== undefined && opts.arg !== null) {
			body = body.concat(uint(D_ARG, opts.arg, true));
		}
		return frame(uint(F_MESSAGE_ID, mid, false).concat(embed(F_DALI, body)));
	}

	function daliArcLevel(mid, lineMask, address, level) {
		return toBytes(dali(mid, lineMask, address,
			{ customCommand: DALI_ARC_LEVEL, arg: clamp(level, 0, DALI_ARC_LEVEL_MAX) }));
	}

	function daliGroupArcLevel(mid, lineMask, group, level) {
		// DALI_ARC_LEVEL to the group address (64 + group).
		return toBytes(dali(mid, lineMask, DALI_GROUP_ADDRESS_BASE + group,
			{ customCommand: DALI_ARC_LEVEL, arg: clamp(level, 0, DALI_ARC_LEVEL_MAX) }));
	}

	function daliCommand(mid, lineMask, address, command, arg) {
		if (typeof command === 'string') {
			var key = command.toLowerCase();
			if (!(key in NAMED_COMMANDS)) throw new Error('unknown DALI command: ' + command);
			command = NAMED_COMMANDS[key];
		}
		return toBytes(dali(mid, lineMask, address, { command: command, arg: arg || 0 }));
	}

	function daliBroadcastScene(mid, lineMask, scene) {
		// Raw "GO TO SCENE X" command (0x10 + scene) to broadcast address 80.
		return toBytes(dali(mid, lineMask, DALI_BROADCAST_ADDRESS, { command: DALI_GO_TO_SCENE_BASE + scene }));
	}

	function daliSceneOnGroup(mid, lineMask, group, scene) {
		// Raw "GO TO SCENE X" command (0x10 + scene) to the group address (64 + group).
		return toBytes(dali(mid, lineMask, DALI_GROUP_ADDRESS_BASE + group, { command: DALI_GO_TO_SCENE_BASE + scene }));
	}

	function dmxLevel(mid, zone, universeMask, channel, repeat, levels, fadeBy10ms) {
		var clamped = [];
		for (var i = 0; i < levels.length; i++) clamped.push(clamp(levels[i], 0, 255));
		var body = uint(X_ZONE, zone, false)
			.concat(uint(X_UNIVERSE_MASK, universeMask, false))
			.concat(uint(X_CHANNEL, channel, false))
			.concat(uint(X_REPEAT, repeat, false))
			.concat(packed(X_LEVEL, clamped))
			.concat(uint(X_FADE, fadeBy10ms || 0, false));
		return toBytes(frame(uint(F_MESSAGE_ID, mid, false).concat(embed(F_DMX, body))));
	}

	function spektraControl(mid, type, zone, index, action) {
		var body = uint(S_TYPE, type, false)
			.concat(uint(S_ZONE, zone, false))
			.concat(uint(S_INDEX, index, false))
			.concat(uint(S_ACTION, action, false));
		return toBytes(frame(uint(F_MESSAGE_ID, mid, false).concat(embed(F_SPEKTRA_CONTROL, body))));
	}

	function spektraStop(mid, zone, lineMask) {
		if (lineMask === undefined) lineMask = 0xff;
		var trigger = uint(T_TYPE, TRIGGER_SPEKTRA_STOP_SEQ, false)
			.concat(uint(T_ZONE, zone, false))
			.concat(uint(T_LINE_MASK, lineMask, false));
		var ext = embed(E_TRIGGER, trigger);
		return toBytes(frame(uint(F_MESSAGE_ID, mid, false).concat(embed(F_EXTERNAL_TRIGGER, ext))));
	}

	function lineMask(line) {
		return 1 << (line - 1);
	}

	var api = {
		daliArcLevel: daliArcLevel,
		daliGroupArcLevel: daliGroupArcLevel,
		daliCommand: daliCommand,
		daliBroadcastScene: daliBroadcastScene,
		daliSceneOnGroup: daliSceneOnGroup,
		dmxLevel: dmxLevel,
		spektraControl: spektraControl,
		spektraStop: spektraStop,
		lineMask: lineMask,
		KEEP_ALIVE: toBytes([0xff, 0xf6]),
		// enums
		SPEKTRA_SEQUENCE: SPEKTRA_SEQUENCE, SPEKTRA_THEME: SPEKTRA_THEME, SPEKTRA_STATIC: SPEKTRA_STATIC,
		SPEKTRA_START: SPEKTRA_START, SPEKTRA_STOP: SPEKTRA_STOP, SPEKTRA_PAUSE: SPEKTRA_PAUSE,
		DALI_MAX_LEVEL: DALI_MAX_LEVEL, DALI_OFF: DALI_OFF
	};

	// Export for Node (CommonJS) and for RTI's global-script engine.
	if (typeof module !== 'undefined' && module.exports) {
		module.exports = api;
	} else {
		root.edidioFrames = api;
	}
})(typeof globalThis !== 'undefined' ? globalThis : this);
