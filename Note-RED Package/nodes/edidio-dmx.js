// DMX action node: write raw channel levels, or paint an RGB colour across a
// line. Configured values are defaults; msg.payload fields override.

const builder = require('../lib/messageBuilder');
const { maskForLine } = require('../lib/lineTypes');
const { pick, num, attachStatus, sendFrame } = require('../lib/nodeCommon');

function parseHex(input) {
	const hex = String(input).replace(/^#/, '').trim();
	if (!/^[0-9a-fA-F]{6}$/.test(hex)) return null;
	return [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)];
}

module.exports = function (RED) {
	function EdidioDmxNode(config) {
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
			const fadeMs = num(pick(p, 'fadeMs', config.fadeMs), 0);
			const fadeTimeBy10ms = Math.round(fadeMs / 10);

			let frame;
			let label;
			try {
				if (action === 'color') {
					const rgb = parseHex(pick(p, 'hex', config.hex) || '');
					if (!rgb) {
						done(new Error('DMX color: hex must be #RRGGBB'));
						return;
					}
					const fixtures = num(pick(p, 'fixtures', config.fixtures), Math.floor(512 / rgb.length));
					const zone = num(pick(p, 'zone', config.zone), 0xff);
					frame = builder.dmxColour({
						zone, universeMask: mask, channel: 1, repeat: fixtures, levels: rgb, fadeTimeBy10ms,
					});
					label = `#${rgb.map((c) => c.toString(16).padStart(2, '0')).join('')} ×${fixtures}`;
				} else {
					// raw levels
					let levels = pick(p, 'levels', config.levels);
					if (typeof levels === 'string') {
						levels = levels.split(',').map((s) => Number(s.trim())).filter((n) => !Number.isNaN(n));
					}
					if (!Array.isArray(levels) || levels.length === 0) {
						done(new Error('DMX level: `levels` must be a non-empty array (0-255)'));
						return;
					}
					levels = levels.map((v) => Math.max(0, Math.min(255, Number(v))));
					const channel = num(pick(p, 'channel', config.channel), 1);
					const repeat = num(pick(p, 'repeat', config.repeat), 1);
					const zone = num(pick(p, 'zone', config.zone), 0);
					frame = builder.dmxColour({
						zone, universeMask: mask, channel, repeat, levels, fadeTimeBy10ms,
					});
					label = `ch ${channel} ×${repeat}`;
				}
			} catch (err) {
				done(err);
				return;
			}

			sendFrame(node, controllerNode, frame, label, msg, send, done);
		});
	}

	RED.nodes.registerType('edidio-dmx', EdidioDmxNode);
};
