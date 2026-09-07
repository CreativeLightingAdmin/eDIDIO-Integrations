// EXAMPLE: binding the platform-independent EdidioDriver to RTI Integration
// Designer 11's JavaScript DDK.
//
// This file is illustrative. The exact global object/function names are provided
// by RTI's DDK and can vary by driver template and IDE version — consult the DDK
// documentation and adjust the `host` adapter and the command hooks accordingly.
// The important part is that all lighting logic lives in driver.js (which is
// unit-tested); this file is only the thin glue to RTI's runtime.

// In RTI's environment these are provided globally; when editing in the DDK you
// typically don't `require`, you concatenate/include edidio_frames.js and
// driver.js into the driver script. Shown here for clarity.
// var frames = edidioFrames;            // from edidio_frames.js
// var EdidioDriver = EdidioDriver;      // from driver.js

// --- host adapter: map the driver's needs onto RTI's runtime APIs ----------
var host = {
	// Transmit bytes to the controller over the DDK's TCP connection.
	// RTI drivers typically expose something like System.write()/Send() bound to
	// the configured connection. Replace with your DDK's send call.
	send: function (bytes) {
		// e.g. System.Device.send(bytes);  // <-- RTI DDK send
	},
	// Update an RTI driver variable for two-way feedback (e.g. a status label).
	setVariable: function (name, value) {
		// e.g. System.setVariable(name, value);  // <-- RTI DDK variable API
	},
	log: function (message) {
		// e.g. System.print(message);  // <-- RTI DDK logging
	},
};

var edidio = new EdidioDriver(host, { keepaliveSeconds: 7 });

// --- connection callbacks (wire these to the DDK's connection events) ------
function onConnected() { edidio.onConnect(); }
function onDisconnected() { edidio.onDisconnect(); }
function onDataReceived(bytes) { edidio.onData(bytes); }

// Call from a repeating DDK timer (~every 7s) to keep the link alive.
function onTimerTick() { edidio.keepAlive(); }

// --- driver command entry points (map to RTI "System Commands") ------------
// Register these as the driver's commands in the DDK; wire their parameters to
// command arguments in Integration Designer.
function cmdSetLevel(line, address, level) { edidio.setLevel(line, address, level); }
function cmdSetGroupLevel(line, group, level) { edidio.setGroupLevel(line, group, level); }
function cmdOn(line, address) { edidio.on(line, address); }
function cmdOff(line, address) { edidio.off(line, address); }
function cmdRecallScene(line, scene) { edidio.recallScene(line, scene); }
function cmdRecallSceneOnGroup(line, group, scene) { edidio.recallScene(line, scene, group); }
function cmdDmxColor(line, hex) { edidio.dmxColor(line, hex); }
function cmdSpektra(zone, target, index, action) { edidio.spektra(zone, target, index, action); }
function cmdSpektraStop(zone) { edidio.spektraStop(zone); }
