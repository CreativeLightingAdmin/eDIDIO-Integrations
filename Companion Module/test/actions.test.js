// Verify Companion actions build the correct eDIDIO frames. Run: node --test
// (The Companion runtime glue in main.js needs Companion to run; this covers the
// action -> frame mapping, which is the module's real logic.)

const test = require('node:test')
const assert = require('node:assert')
const frames = require('../src/edidio_frames.js')
const { buildFrame, getActionDefinitions } = require('../src/actions.js')

const MID = 7
const hex = (b) => Buffer.from(b).toString('hex')

test('set_level', () => {
	assert.strictEqual(
		hex(buildFrame('set_level', { line: 1, address: 5, level: 200 }, MID)),
		hex(frames.daliArcLevel(MID, frames.lineMask(1), 5, 200))
	)
})

test('set_group_level', () => {
	assert.strictEqual(
		hex(buildFrame('set_group_level', { line: 1, group: 3, level: 128 }, MID)),
		hex(frames.daliGroupArcLevel(MID, frames.lineMask(1), 3, 128))
	)
})

test('dali_command (named)', () => {
	assert.strictEqual(
		hex(buildFrame('dali_command', { line: 2, address: 10, command: 'max' }, MID)),
		hex(frames.daliCommand(MID, frames.lineMask(2), 10, 'max'))
	)
})

test('recall_scene broadcast', () => {
	assert.strictEqual(
		hex(buildFrame('recall_scene', { line: 1, scene: 3, group: '' }, MID)),
		hex(frames.daliBroadcastScene(MID, frames.lineMask(1), 3))
	)
})

test('recall_scene on group', () => {
	assert.strictEqual(
		hex(buildFrame('recall_scene', { line: 1, scene: 3, group: '4' }, MID)),
		hex(frames.daliSceneOnGroup(MID, frames.lineMask(1), 4, 3))
	)
})

test('dmx_color', () => {
	assert.strictEqual(
		hex(buildFrame('dmx_color', { line: 2, hex: '#FF0000' }, MID)),
		hex(frames.dmxLevel(MID, 0xff, frames.lineMask(2), 1, Math.floor(512 / 3), [255, 0, 0], 0))
	)
})

test('spektra', () => {
	assert.strictEqual(
		hex(buildFrame('spektra', { zone: 1, type: 'sequence', index: 2, action: 'start' }, MID)),
		hex(frames.spektraControl(MID, frames.SPEKTRA_SEQUENCE, 1, 2, frames.SPEKTRA_START))
	)
})

test('spektra_stop', () => {
	assert.strictEqual(
		hex(buildFrame('spektra_stop', { zone: 1 }, MID)),
		hex(frames.spektraStop(MID, 1))
	)
})

test('unknown action throws', () => {
	assert.throws(() => buildFrame('nope', {}, MID))
})

test('action definitions expose all actions with callbacks', () => {
	const captured = []
	const self = { dispatch: (id, opt) => captured.push([id, opt]) }
	const defs = getActionDefinitions(self)
	const ids = Object.keys(defs)
	assert.ok(ids.includes('set_level') && ids.includes('recall_scene') && ids.includes('spektra'))
	// each definition has a name, options array, and a working callback
	for (const id of ids) {
		assert.ok(defs[id].name && Array.isArray(defs[id].options) && typeof defs[id].callback === 'function')
	}
	defs.set_level.callback({ options: { line: 1, address: 5, level: 254 } })
	assert.deepStrictEqual(captured.at(-1), ['set_level', { line: 1, address: 5, level: 254 }])
})
