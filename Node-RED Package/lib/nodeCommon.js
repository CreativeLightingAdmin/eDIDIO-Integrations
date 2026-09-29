// Shared helpers for eDIDIO action nodes: connection-state status display and a
// uniform "build a frame and send it" flow with consistent error handling.

// Read a value from msg.payload (preferred) falling back to the node's
// configured default. Config values arrive as strings from the editor, so
// numeric fields are coerced by the caller.
function pick(payload, key, fallback) {
	if (payload && typeof payload === 'object' && payload[key] !== undefined && payload[key] !== '') {
		return payload[key];
	}
	return fallback;
}

function num(value, fallback) {
	if (value === undefined || value === null || value === '') return fallback;
	const n = Number(value);
	return Number.isNaN(n) ? fallback : n;
}

// Mirror the controller connection state in the node's status dot.
function attachStatus(node, controllerNode) {
	function render(state) {
		if (state && state.connected) {
			node.status({ fill: 'green', shape: 'dot', text: 'connected' });
		} else {
			node.status({ fill: 'red', shape: 'ring', text: 'disconnected' });
		}
	}
	render({ connected: controllerNode.isConnected() });
	const handler = (state) => render(state);
	controllerNode.on('edidio-state', handler);
	node.on('close', () => controllerNode.removeListener('edidio-state', handler));
}

// Send a framed message and report the outcome on the node + downstream.
// `describe` returns a short status label for the sent command.
async function sendFrame(node, controllerNode, frame, describe, msg, send, done) {
	if (!controllerNode.isConnected()) {
		node.status({ fill: 'red', shape: 'ring', text: 'not connected' });
		done(new Error('eDIDIO controller not connected'));
		return;
	}
	try {
		const sent = await controllerNode.send(frame);
		if (!sent) {
			node.status({ fill: 'red', shape: 'ring', text: 'send failed' });
			done(new Error('eDIDIO send failed (connection dropped)'));
			return;
		}
		node.status({ fill: 'green', shape: 'dot', text: describe });
		msg.payload = Object.assign({ sent: true }, msg.payload);
		send(msg);
		done();
	} catch (err) {
		node.status({ fill: 'red', shape: 'ring', text: 'error' });
		done(err);
	}
}

module.exports = { pick, num, attachStatus, sendFrame };
