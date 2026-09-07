// Tests for the OBS event -> eDIDIO frame mapper. Run: node --test
// (The obs-websocket glue needs a live OBS; this covers the mapping — decode
// each frame to assert the command.)

const test = require('node:test')
const assert = require('node:assert')

const pb = require('../src/edidio/eDS10_ProtocolBuffer_pb.js')
const { handleSceneChange, handleStream, handleRecord, buildAction } = require('../src/mapper')

const CONFIG = require('../src/triggers.example.json')

function decode(frame) {
	assert.strictEqual(frame[0], 0xcd)
	const len = (frame[1] << 8) | frame[2]
	assert.strictEqual(len, frame.length - 3)
	return pb.EdidioMessage.deserializeBinary(new Uint8Array(frame.slice(3)))
}

test('scene change -> DALI scene', () => {
	const r = handleSceneChange(CONFIG, 'Starting Soon')
	const d = decode(r.frame).getDaliMessage()
	// GO TO SCENE 1 (0x10 + 1) broadcast to address 80
	assert.strictEqual(d.getAddress(), 80)
	assert.strictEqual(d.getCommand(), 0x10 + 1)
})

test('scene change -> DMX colour', () => {
	const r = handleSceneChange(CONFIG, 'Live')
	const d = decode(r.frame).getDmxMessage()
	assert.deepStrictEqual(d.getLevelList(), [0, 0x44, 0xff])
})

test('unmapped scene -> null', () => {
	assert.strictEqual(handleSceneChange(CONFIG, 'Some Other Scene'), null)
})

test('stream start -> spektra sequence', () => {
	const r = handleStream(CONFIG, true)
	assert.ok(decode(r.frame).getSpektraControl())
})

test('stream stop -> spektra stop (external trigger)', () => {
	const r = handleStream(CONFIG, false)
	assert.ok(decode(r.frame).getExternalTrigger())
})

test('record start/stop -> on/off indicator', () => {
	const on = handleRecord(CONFIG, true)
	let d = decode(on.frame).getDaliMessage()
	assert.strictEqual(d.getAddress(), 10)
	assert.strictEqual(d.getCommand(), builderMax()) // DALI_MAX_LEVEL
	const off = handleRecord(CONFIG, false)
	d = decode(off.frame).getDaliMessage()
	assert.strictEqual(d.getAddress(), 10)
})

function builderMax() {
	return require('../src/edidio/messageBuilder').DALICommandType.DALI_MAX_LEVEL
}

test('buildAction validates', () => {
	assert.throws(() => buildAction({ action: 'scene', scene: 99 }))
	assert.throws(() => buildAction({ action: 'color', hex: 'nope' }))
	assert.throws(() => buildAction({ action: 'bogus' }))
})

test('empty config sections -> null (no crash)', () => {
	assert.strictEqual(handleStream({}, true), null)
	assert.strictEqual(handleRecord({}, false), null)
	assert.strictEqual(handleSceneChange({}, 'Live'), null)
})
