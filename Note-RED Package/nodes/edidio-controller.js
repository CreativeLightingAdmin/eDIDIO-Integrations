// Config node: owns a single, shared eDIDIO controller connection that action
// nodes send through. Manages connect/reconnect/heartbeat and re-broadcasts
// connection state so action nodes can reflect it in their status.

const { ControllerConnection } = require('../lib/connection');

module.exports = function (RED) {
	function EdidioControllerNode(config) {
		RED.nodes.createNode(this, config);
		const node = this;

		node.host = config.host;
		node.port = config.port ? Number(config.port) : undefined;
		node.useTLS = config.useTLS === true || config.useTLS === 'true';
		node.heartbeatMs = config.heartbeatMs ? Number(config.heartbeatMs) : 7000;

		node.conn = new ControllerConnection(node.host, {
			port: node.port,
			useTLS: node.useTLS,
			heartbeatMs: node.heartbeatMs,
		});

		// Re-emit connection lifecycle so action nodes can subscribe.
		node.conn.on('connect', () => node.emit('edidio-state', { connected: true }));
		node.conn.on('disconnect', () => node.emit('edidio-state', { connected: false }));
		node.conn.on('error', (err) => node.emit('edidio-state', { connected: false, error: err }));

		// Kick off the initial connection. Failures are non-fatal: the connection
		// retries in the background with exponential backoff.
		node.conn.connect().catch(() => {
			/* error surfaced via 'edidio-state'; reconnect loop handles retries */
		});

		// Convenience passthroughs for action nodes.
		node.isConnected = () => node.conn.connected;
		node.send = (frame) => node.conn.send(frame);
		node.lineTypes = () => node.conn.lineTypes;

		node.on('close', function (done) {
			node.conn.removeAllListeners();
			node.conn.disconnect();
			done();
		});
	}

	RED.nodes.registerType('edidio-controller', EdidioControllerNode);
};
