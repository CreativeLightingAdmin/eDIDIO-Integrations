// SpektraPlus action node: start/stop/pause a stored sequence, theme, or static
// scene on a zone. Configured values are defaults; msg.payload fields override.

const builder = require('../lib/messageBuilder');
const { pick, num, attachStatus, sendFrame } = require('../lib/nodeCommon');

const TARGETS = {
	sequence: builder.SpektraTargetType.SEQUENCE,
	theme: builder.SpektraTargetType.THEME,
	static: builder.SpektraTargetType.STATIC,
};
const ACTIONS = {
	start: builder.SpektraActionType.START,
	stop: builder.SpektraActionType.STOP,
	pause: builder.SpektraActionType.PAUSE,
};

module.exports = function (RED) {
	function EdidioSpektraNode(config) {
		RED.nodes.createNode(this, config);
		const node = this;
		const controllerNode = RED.nodes.getNode(config.controller);

		if (!controllerNode) {
			node.status({ fill: 'red', shape: 'ring', text: 'no controller' });
			return;
		}
		attachStatus(node, controllerNode);

		node.on('input', function (msg, send, done) {
			const p = msg.payload || {};
			const zone = num(pick(p, 'zone', config.zone), 0);
			const actionName = String(pick(p, 'action', config.action) || 'start').toLowerCase();

			let frame;
			let label;
			try {
				if (actionName === 'stop_off') {
					// Full stop that also turns the output off (SPEKTRA_STOP_SEQ trigger).
					frame = builder.spektraStop({ zone });
					label = `zone ${zone} stop+off`;
				} else {
					// `target` is the configured type; `type` is the payload override
					// key (config.type is reserved by Node-RED for the node's type).
					const typeName = String(pick(p, 'type', config.target) || 'sequence').toLowerCase();
					if (!(typeName in TARGETS)) {
						done(new Error(`Unknown Spektra type: ${typeName}`));
						return;
					}
					if (!(actionName in ACTIONS)) {
						done(new Error(`Unknown Spektra action: ${actionName}`));
						return;
					}
					const index = num(pick(p, 'index', config.index), 0);
					frame = builder.spektraControl({
						type: TARGETS[typeName], zone, index, action: ACTIONS[actionName],
					});
					label = `${typeName} ${index} ${actionName} (zone ${zone})`;
				}
			} catch (err) {
				done(err);
				return;
			}

			sendFrame(node, controllerNode, frame, label, msg, send, done);
		});
	}

	RED.nodes.registerType('edidio-spektra', EdidioSpektraNode);
};
