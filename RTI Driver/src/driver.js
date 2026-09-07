// eDIDIO driver logic for RTI Integration Designer 11 (JavaScript DDK).
//
// This module holds the platform-independent driver behaviour: it turns RTI
// driver commands into eDIDIO frames, sends them via a transport, maintains a
// keep-alive heartbeat, and mirrors connection state into a driver variable for
// two-way feedback.
//
// RTI's DDK provides the actual TCP transport and variable/print APIs. To keep
// this logic testable off-device, those are injected as a small `host` object:
//   host.send(bytes)                 -> transmit bytes to the controller
//   host.setVariable(name, value)    -> update an RTI driver variable (optional)
//   host.log(message)                -> diagnostic logging (optional)
//
// See README.md for how to bind `host` to RTI's real send/variable functions.

(function (root) {
	'use strict';

	var frames = (typeof module !== 'undefined' && module.exports)
		? require('./edidio_frames.js')
		: root.edidioFrames;

	function parseHex(value) {
		var hex = String(value).replace(/^#/, '');
		if (!/^[0-9a-fA-F]{6}$/.test(hex)) throw new Error('colour must be #RRGGBB');
		return [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)];
	}

	var SPEKTRA_TARGET = { sequence: frames.SPEKTRA_SEQUENCE, theme: frames.SPEKTRA_THEME, static: frames.SPEKTRA_STATIC };
	var SPEKTRA_ACTION = { start: frames.SPEKTRA_START, stop: frames.SPEKTRA_STOP, pause: frames.SPEKTRA_PAUSE };

	function EdidioDriver(host, options) {
		options = options || {};
		this.host = host || {};
		this.keepaliveSeconds = options.keepaliveSeconds || 7;
		this.connected = false;
		this._mid = 0;
	}

	// --- lifecycle / feedback ---------------------------------------------
	EdidioDriver.prototype.onConnect = function () {
		this.connected = true;
		this._setVar('ConnectionStatus', 'Connected');
		this._log('eDIDIO connected');
	};

	EdidioDriver.prototype.onDisconnect = function () {
		this.connected = false;
		this._setVar('ConnectionStatus', 'Disconnected');
		this._log('eDIDIO disconnected');
	};

	// Called by RTI's periodic timer to keep the socket alive.
	EdidioDriver.prototype.keepAlive = function () {
		if (this.connected) this._send(frames.KEEP_ALIVE);
	};

	// Called by RTI when bytes arrive from the controller. This control-focused
	// driver doesn't parse the protobuf responses; receiving anything confirms
	// the link is live. (Full state decoding is a future enhancement.)
	EdidioDriver.prototype.onData = function (bytes) {
		if (bytes && bytes.length) this._setVar('LastActivity', Date.now());
	};

	// --- DALI --------------------------------------------------------------
	EdidioDriver.prototype.setLevel = function (line, address, level) {
		this._send(frames.daliArcLevel(this._nextId(), frames.lineMask(line), address, level));
	};
	EdidioDriver.prototype.setGroupLevel = function (line, group, level) {
		this._send(frames.daliGroupArcLevel(this._nextId(), frames.lineMask(line), group, level));
	};
	EdidioDriver.prototype.on = function (line, address) {
		this._send(frames.daliCommand(this._nextId(), frames.lineMask(line), address, 'on'));
	};
	EdidioDriver.prototype.off = function (line, address) {
		this._send(frames.daliCommand(this._nextId(), frames.lineMask(line), address, 'off'));
	};
	EdidioDriver.prototype.command = function (line, address, cmd, arg) {
		this._send(frames.daliCommand(this._nextId(), frames.lineMask(line), address, cmd, arg || 0));
	};
	EdidioDriver.prototype.recallScene = function (line, scene, group) {
		if (group === undefined || group === null || group === '') {
			this._send(frames.daliBroadcastScene(this._nextId(), frames.lineMask(line), scene));
		} else {
			this._send(frames.daliSceneOnGroup(this._nextId(), frames.lineMask(line), group, scene));
		}
	};

	// --- DMX ---------------------------------------------------------------
	EdidioDriver.prototype.dmxLevels = function (line, levels, channel, repeat, zone, fadeMs) {
		this._send(frames.dmxLevel(this._nextId(), zone || 0, frames.lineMask(line),
			channel || 1, repeat || 1, levels, Math.floor((fadeMs || 0) / 10)));
	};
	EdidioDriver.prototype.dmxColor = function (line, hex, fixtures, zone, fadeMs) {
		var rgb = parseHex(hex);
		if (fixtures === undefined || fixtures === null) fixtures = Math.floor(512 / rgb.length);
		if (zone === undefined || zone === null) zone = 0xff;
		this._send(frames.dmxLevel(this._nextId(), zone, frames.lineMask(line),
			1, fixtures, rgb, Math.floor((fadeMs || 0) / 10)));
	};

	// --- SpektraPlus -------------------------------------------------------
	EdidioDriver.prototype.spektra = function (zone, target, index, action) {
		var t = SPEKTRA_TARGET[String(target).toLowerCase()];
		var a = SPEKTRA_ACTION[String(action).toLowerCase()];
		if (t === undefined) throw new Error('unknown Spektra target: ' + target);
		if (a === undefined) throw new Error('unknown Spektra action: ' + action);
		this._send(frames.spektraControl(this._nextId(), t, zone, index || 0, a));
	};
	EdidioDriver.prototype.spektraStop = function (zone) {
		this._send(frames.spektraStop(this._nextId(), zone));
	};

	// --- internals ---------------------------------------------------------
	EdidioDriver.prototype._send = function (bytes) {
		if (this.host && this.host.send) this.host.send(bytes);
	};
	EdidioDriver.prototype._setVar = function (name, value) {
		if (this.host && this.host.setVariable) this.host.setVariable(name, value);
	};
	EdidioDriver.prototype._log = function (message) {
		if (this.host && this.host.log) this.host.log(message);
	};
	EdidioDriver.prototype._nextId = function () {
		this._mid = (this._mid + 1) & 0xffffff;
		return this._mid;
	};

	var api = { EdidioDriver: EdidioDriver };
	if (typeof module !== 'undefined' && module.exports) {
		module.exports = api;
	} else {
		root.EdidioDriver = EdidioDriver;
	}
})(typeof globalThis !== 'undefined' ? globalThis : this);
