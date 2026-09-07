// DMX control: write raw channel levels, or paint an RGB colour across a line.
//
// A DMX universe has 512 channels (1-based). `levels` is written starting at
// `channel`; `repeat` tiles that pattern to cover many identical fixtures.

const express = require('express');
const { asyncHandler, ApiError } = require('../middleware/errors');
const { int, byteArray, dispatch, assertLineType, maskForLine } = require('./helpers');
const builder = require('../edidio/messageBuilder');

const router = express.Router();

// Parse "#RRGGBB" / "RRGGBB" into [r, g, b].
function parseHex(input) {
	const hex = String(input).replace(/^#/, '').trim();
	if (!/^[0-9a-fA-F]{6}$/.test(hex)) return null;
	return [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)];
}

// POST /api/v1/dmx/level — write raw channel levels on a line.
// body: { line, levels[], channel?=1, repeat?=1, zone?=0, fadeMs?, controller? }
router.post(
	'/dmx/level',
	asyncHandler(async (req, res) => {
		const line = int(req.body.line, 'line', { min: 1, max: 4 });
		const levels = byteArray(req.body.levels, 'levels');
		const channel = int(req.body.channel, 'channel', { min: 1, max: 512, required: false, def: 1 });
		const repeat = int(req.body.repeat, 'repeat', { min: 1, max: 512, required: false, def: 1 });
		const zone = int(req.body.zone, 'zone', { min: 0, max: 255, required: false, def: 0 });
		const fadeMs = int(req.body.fadeMs, 'fadeMs', { min: 0, max: 655350, required: false, def: 0 });
		const fadeTimeBy10ms = Math.round(fadeMs / 10);

		const result = await dispatch(req, 'DMX', (conn) => {
			assertLineType(conn, line, 'DMX');
			return builder.dmxColour({
				zone,
				universeMask: maskForLine(line),
				channel,
				repeat,
				levels,
				fadeTimeBy10ms,
			});
		});
		res.json({ ...result, line, channel, repeat, zone, levels });
	}),
);

// POST /api/v1/dmx/color — paint an RGB colour across a line's fixtures.
// body: { line, hex, fixtures?, zone?=0xFF, fadeMs?, controller? }
router.post(
	'/dmx/color',
	asyncHandler(async (req, res) => {
		const line = int(req.body.line, 'line', { min: 1, max: 4 });
		const rgb = parseHex(req.body.hex ?? '');
		if (!rgb) throw new ApiError(400, '`hex` must be a #RRGGBB colour');
		// Default: fill a 512-channel universe with the RGB triplet.
		const fixtures = int(req.body.fixtures, 'fixtures', {
			min: 1,
			max: 170,
			required: false,
			def: Math.floor(512 / rgb.length),
		});
		const zone = int(req.body.zone, 'zone', { min: 0, max: 255, required: false, def: 0xff });
		const fadeMs = int(req.body.fadeMs, 'fadeMs', { min: 0, max: 655350, required: false, def: 0 });

		const result = await dispatch(req, 'DMX', (conn) => {
			assertLineType(conn, line, 'DMX');
			return builder.dmxColour({
				zone,
				universeMask: maskForLine(line),
				channel: 1,
				repeat: fixtures,
				levels: rgb,
				fadeTimeBy10ms: Math.round(fadeMs / 10),
			});
		});
		res.json({ ...result, line, rgb, fixtures });
	}),
);

module.exports = router;
