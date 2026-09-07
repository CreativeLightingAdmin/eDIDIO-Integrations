const test = require('node:test')
const assert = require('node:assert')
const pb = require('../src/edidio/eDS10_ProtocolBuffer_pb.js')
const { parseCommand, handleCommand } = require('../src/mapper')

function decode(frame) {
	assert.strictEqual(frame[0], 0xcd)
	const len = (frame[1] << 8) | frame[2]
	assert.strictEqual(len, frame.length - 3)
	return pb.EdidioMessage.deserializeBinary(new Uint8Array(frame.slice(3)))
}

test('parseCommand strips @botname', () => {
	assert.deepStrictEqual(parseCommand('/scene@mybot 3'), { name: 'scene', args: ['3'] })
	assert.deepStrictEqual(parseCommand('/on 5'), { name: 'on', args: ['5'] })
	assert.strictEqual(parseCommand('hello'), null)
})

test('/help returns help text, no frame', () => {
	const r = handleCommand('/help')
	assert.ok(r.reply.includes('eDIDIO'))
	assert.strictEqual(r.frame, undefined)
})

test('/scene builds broadcast scene', () => {
	const r = handleCommand('/scene 3')
	const d = decode(r.frame).getDaliMessage()
	// GO TO SCENE 3 (0x10 + 3) broadcast to address 80
	assert.strictEqual(d.getAddress(), 80)
	assert.strictEqual(d.getCommand(), 0x10 + 3)
})

test('/level builds arc level with default line', () => {
	const r = handleCommand('/level 5 200')
	const d = decode(r.frame).getDaliMessage()
	assert.strictEqual(d.getAddress(), 5)
	assert.strictEqual(d.getArg(), 200)
	assert.strictEqual(d.getLineMask(), 1)
})

test('/group builds group level', () => {
	const r = handleCommand('/group 0 128')
	const d = decode(r.frame).getDaliMessage()
	assert.strictEqual(d.getCustomCommand(), 0) // DALI_ARC_LEVEL at group address
	assert.strictEqual(d.getAddress(), 64) // 64 + group 0
	assert.strictEqual(d.getArg(), 128)
})

test('/on and /off', () => {
	const on = handleCommand('/on 5')
	assert.strictEqual(decode(on.frame).getDaliMessage().getCommand(), require('../src/edidio/messageBuilder').DALICommandType.DALI_MAX_LEVEL)
	const off = handleCommand('/off 5')
	assert.strictEqual(decode(off.frame).getDaliMessage().getCommand(), require('../src/edidio/messageBuilder').DALICommandType.DALI_OFF)
})

test('/color builds DMX', () => {
	const r = handleCommand('/color #FF0000')
	const d = decode(r.frame).getDmxMessage()
	assert.deepStrictEqual(d.getLevelList(), [255, 0, 0])
})

test('/color invalid hex -> usage reply, no frame', () => {
	const r = handleCommand('/color nope')
	assert.ok(r.reply.includes('Usage'))
	assert.strictEqual(r.frame, undefined)
})

test('/seq builds spektra sequence', () => {
	const r = handleCommand('/seq 0 1')
	assert.ok(decode(r.frame).getSpektraControl())
})

test('unknown command returns null', () => {
	assert.strictEqual(handleCommand('/nope'), null)
})

test('out of range -> error reply', () => {
	const r = handleCommand('/scene 99')
	assert.ok(r.reply.includes('0-15'))
	assert.strictEqual(r.frame, undefined)
})
