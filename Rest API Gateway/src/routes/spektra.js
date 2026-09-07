// SpektraPlus playback control: start/stop/pause a stored sequence, theme, or
// static scene on a zone. This is the high-level "scenes & effects" layer that
// mirrors what the SpektraPlus app triggers.

const express = require('express');
const { asyncHandler, ApiError } = require('../middleware/errors');
const { int, dispatch } = require('./helpers');
const builder = require('../edidio/messageBuilder');

const router = express.Router();
const { SpektraTargetType, SpektraActionType } = builder;

const TARGETS = {
	sequence: SpektraTargetType.SEQUENCE,
	theme: SpektraTargetType.THEME,
	static: SpektraTargetType.STATIC,
};

const ACTIONS = {
	start: SpektraActionType.START,
	stop: SpektraActionType.STOP,
	pause: SpektraActionType.PAUSE,
};

function lookup(map, value, field) {
	if (value === undefined || value === null || value === '') {
		throw new ApiError(400, `Missing required field: ${field}`);
	}
	const key = String(value).toLowerCase();
	if (!(key in map)) {
		throw new ApiError(400, `Invalid ${field} "${value}". Known: ${Object.keys(map).join(', ')}`);
	}
	return map[key];
}

// POST /api/v1/spektra — control SpektraPlus playback on a zone.
// body: { zone, type: sequence|theme|static, index, action: start|stop|pause, controller? }
router.post(
	'/spektra',
	asyncHandler(async (req, res) => {
		const zone = int(req.body.zone, 'zone', { min: 0, max: 255 });
		const type = lookup(TARGETS, req.body.type, 'type');
		const action = lookup(ACTIONS, req.body.action, 'action');
		const index = int(req.body.index, 'index', { min: 0, max: 65535, required: false, def: 0 });

		// SpektraControl frames aren't line-specific, so no line-type check.
		const result = await dispatch(req, null, () =>
			builder.spektraControl({ type, zone, index, action }),
		);
		res.json({ ...result, zone, type: req.body.type, index, action: req.body.action });
	}),
);

// POST /api/v1/spektra/stop — stop playback on a zone AND turn the output off,
// matching how the SpektraPlus app stops a running effect.
// body: { zone, controller? }
router.post(
	'/spektra/stop',
	asyncHandler(async (req, res) => {
		const zone = int(req.body.zone, 'zone', { min: 0, max: 255, required: false, def: 0 });
		const result = await dispatch(req, null, () => builder.spektraStop({ zone }));
		res.json({ ...result, zone });
	}),
);

module.exports = router;
