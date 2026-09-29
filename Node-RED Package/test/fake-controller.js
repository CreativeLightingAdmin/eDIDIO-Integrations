// Test double for the edidio-controller config node: captures frames instead of
// opening a socket, and reports a configurable connection state. Registered under
// the real type name so action nodes resolve it transparently.

module.exports = function (RED) {
	function FakeController(config) {
		RED.nodes.createNode(this, config);
		const node = this;
		node.sent = [];
		node._connected = config.connected !== false;
		node.isConnected = () => node._connected;
		node.send = (frame) => {
			node.sent.push(Buffer.from(frame));
			return Promise.resolve(node._connected);
		};
		node.lineTypes = () => null;
	}
	RED.nodes.registerType('edidio-controller', FakeController);
};
