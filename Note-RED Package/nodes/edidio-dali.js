// DALI action node: level, group level, on/off, standard command, and scene
// recall. Configured values are defaults; matching msg.payload fields override
// them so a single node can be driven dynamically (e.g. {address:5, level:100}).

const builder = require('../lib/messageBuilder');
const { maskForLine } = require('../lib/lineTypes');
const { pick, num, attachStatus, sendFrame } = require('../lib/nodeCommon');

const NAMED_COMMANDS = {
	off: builder.DALICommandType.DALI_OFF,
	on: builder.DALICommandType.DALI_MAX_LEVEL,
	max: builder.DALICommandType.DALI_MAX_LEVEL,
	min: builder.DALICommandType.DALI_MIN_LEVEL,
	fade_up: builder.DALICommandType.DALI_FADE_UP,
	fade_down: builder.DALICommandType.DALI_FADE_DOWN,
	step_up: builder.DALICommandType.DALI_STEP_UP,
	step_down: builder.DALICommandType.DALI_STEP_DOWN,
	recall_last: builder.DALICommandType.DALI_RECALL_LAST_ACTIVE_LEVEL,
	identify: builder.DALICommandType.DALI_IDENTIFY_DEVICE,
};

function resolveCommand(value) {
	if (typeof value === 'number') return value;
	if (typeof value === 'string' && /^\d+$/.test(value)) return Number(value);
	if (typeof value === 'string' && value.toLowerCase() in NAMED_COMMANDS) {
		return NAMED_COMMANDS[value.toLowerCase()];
	}
	return null;
}

module.exports = function (RED) {
	function EdidioDaliNode(config) {
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
			const action = pick(p, 'action', config.action) || 'level';
			const line = num(pick(p, 'line', config.line), 1);
			const mask = maskForLine(line);

			let frame;
			let label;
			try {
				switch (action) {
					case 'level': {
						const address = num(pick(p, 'address', config.address), 0);
						const level = clampLevel(num(pick(p, 'level', config.level), 0));
						frame = builder.daliArcLevel({ address, level, lineMask: mask });
						label = `addr ${address} → ${level}`;
						break;
					}
					case 'group_level': {
						const group = num(pick(p, 'group', config.group), 0);
						const level = clampLevel(num(pick(p, 'level', config.level), 0));
						frame = builder.daliGroupArcLevel({ group, level, lineMask: mask });
						label = `group ${group} → ${level}`;
						break;
					}
					case 'onoff': {
						const address = num(pick(p, 'address', config.address), 0);
						const on = truthy(pick(p, 'value', config.level));
						frame = builder.daliArcLevel({ address, level: on ? 254 : 0, lineMask: mask });
						label = `addr ${address} ${on ? 'on' : 'off'}`;
						break;
					}
					case 'group_onoff': {
						const group = num(pick(p, 'group', config.group), 0);
						const on = truthy(pick(p, 'value', config.level));
						frame = builder.daliGroupArcLevel({ group, level: on ? 254 : 0, lineMask: mask });
						label = `group ${group} ${on ? 'on' : 'off'}`;
						break;
					}
					case 'command': {
						const address = num(pick(p, 'address', config.address), 0);
						const command = resolveCommand(pick(p, 'command', config.command));
						if (command === null) {
							done(new Error(`Unknown DALI command: ${pick(p, 'command', config.command)}`));
							return;
						}
						const arg = num(pick(p, 'arg', config.arg), 0);
						frame = builder.daliCommand({ address, command, arg, lineMask: mask });
						label = `addr ${address} cmd ${command}`;
						break;
					}
					case 'scene': {
						const scene = num(pick(p, 'scene', config.scene), 0);
						const groupRaw = pick(p, 'group', config.group);
						if (groupRaw === undefined || groupRaw === '' || groupRaw === null) {
							frame = builder.daliBroadcastScene({ scene, lineMask: mask });
							label = `scene ${scene} (line ${line})`;
						} else {
							const group = num(groupRaw, 0);
							frame = builder.daliSceneOnGroup({ group, scene, lineMask: mask });
							label = `scene ${scene} on group ${group}`;
						}
						break;
					}
					default:
						done(new Error(`Unknown DALI action: ${action}`));
						return;
				}
			} catch (err) {
				done(err);
				return;
			}

			sendFrame(node, controllerNode, frame, label, msg, send, done);
		});
	}

	RED.nodes.registerType('edidio-dali', EdidioDaliNode);
};

function clampLevel(v) {
	return Math.max(0, Math.min(254, v));
}

function truthy(v) {
	if (typeof v === 'string') return !(v === '0' || v.toLowerCase() === 'false' || v === '');
	return Boolean(v);
}
