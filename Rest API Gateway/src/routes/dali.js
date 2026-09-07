// DALI control: arc levels, group levels, named commands, and scene recall.
//
// Lines are 1-4 (daughter-board slots); DALI short addresses are 0-63; groups
// and scenes are 0-15; arc levels are 0-254.

const express = require('express');
const { asyncHandler, ApiError } = require('../middleware/errors');
const { int, dispatch, assertLineType, maskForLine } = require('./helpers');
const builder = require('../edidio/messageBuilder');

const router = express.Router();
const { DALICommandType } = builder;

// Friendly names for the DALI standard commands most useful over REST. Callers
// may also pass a raw integer command code.
const NAMED_COMMANDS = {
	off: DALICommandType.DALI_OFF,
	on: DALICommandType.DALI_MAX_LEVEL, // "on" == max level, matching the app
	max: DALICommandType.DALI_MAX_LEVEL,
	min: DALICommandType.DALI_MIN_LEVEL,
	fade_up: DALICommandType.DALI_FADE_UP,
	fade_down: DALICommandType.DALI_FADE_DOWN,
	step_up: DALICommandType.DALI_STEP_UP,
	step_down: DALICommandType.DALI_STEP_DOWN,
	step_down_off: DALICommandType.DALI_STEP_DOWN_OFF,
	on_step_up: DALICommandType.DALI_ON_STEP_UP,
	recall_last: DALICommandType.DALI_RECALL_LAST_ACTIVE_LEVEL,
	identify: DALICommandType.DALI_IDENTIFY_DEVICE,
};

function resolveCommand(value) {
	if (value === undefined || value === null || value === '') {
		throw new ApiError(400, 'Missing required field: command');
	}
	if (typeof value === 'string' && !/^\d+$/.test(value)) {
		const key = value.toLowerCase();
		if (!(key in NAMED_COMMANDS)) {
			throw new ApiError(400, `Unknown command "${value}". Known: ${Object.keys(NAMED_COMMANDS).join(', ')}`);
		}
		return NAMED_COMMANDS[key];
	}
	return int(value, 'command', { min: 0, max: 255 });
}

// POST /api/v1/dali/level — set one address to an arc level.
// body: { line, address, level, controller? }
router.post(
	'/dali/level',
	asyncHandler(async (req, res) => {
		const line = int(req.body.line, 'line', { min: 1, max: 4 });
		const address = int(req.body.address, 'address', { min: 0, max: 63 });
		const level = int(req.body.level, 'level', { min: 0, max: 254 });
		const result = await dispatch(req, 'DALI', (conn) => {
			assertLineType(conn, line, 'DALI');
			return builder.daliArcLevel({ address, level, lineMask: maskForLine(line) });
		});
		res.json({ ...result, line, address, level });
	}),
);

// POST /api/v1/dali/group/level — set a whole DALI group to an arc level.
// body: { line, group, level, controller? }
router.post(
	'/dali/group/level',
	asyncHandler(async (req, res) => {
		const line = int(req.body.line, 'line', { min: 1, max: 4 });
		const group = int(req.body.group, 'group', { min: 0, max: 15 });
		const level = int(req.body.level, 'level', { min: 0, max: 254 });
		const result = await dispatch(req, 'DALI', (conn) => {
			assertLineType(conn, line, 'DALI');
			return builder.daliGroupArcLevel({ group, level, lineMask: maskForLine(line) });
		});
		res.json({ ...result, line, group, level });
	}),
);

// POST /api/v1/dali/command — send a named/standard DALI command to an address.
// body: { line, address, command, arg?, controller? }
router.post(
	'/dali/command',
	asyncHandler(async (req, res) => {
		const line = int(req.body.line, 'line', { min: 1, max: 4 });
		const address = int(req.body.address, 'address', { min: 0, max: 63 });
		const command = resolveCommand(req.body.command);
		const arg = int(req.body.arg, 'arg', { min: 0, max: 255, required: false, def: 0 });
		const result = await dispatch(req, 'DALI', (conn) => {
			assertLineType(conn, line, 'DALI');
			return builder.daliCommand({ address, command, arg, lineMask: maskForLine(line) });
		});
		res.json({ ...result, line, address, command, arg });
	}),
);

// POST /api/v1/dali/scene — recall a stored DALI scene.
// Broadcasts across the line, or targets a group when `group` is supplied.
// body: { line, scene, group?, controller? }
router.post(
	'/dali/scene',
	asyncHandler(async (req, res) => {
		const line = int(req.body.line, 'line', { min: 1, max: 4 });
		const scene = int(req.body.scene, 'scene', { min: 0, max: 15 });
		const hasGroup = req.body.group !== undefined && req.body.group !== null && req.body.group !== '';
		const group = hasGroup ? int(req.body.group, 'group', { min: 0, max: 15 }) : null;
		const result = await dispatch(req, 'DALI', (conn) => {
			assertLineType(conn, line, 'DALI');
			return group === null
				? builder.daliBroadcastScene({ scene, lineMask: maskForLine(line) })
				: builder.daliSceneOnGroup({ group, scene, lineMask: maskForLine(line) });
		});
		res.json({ ...result, line, scene, group });
	}),
);

module.exports = router;
