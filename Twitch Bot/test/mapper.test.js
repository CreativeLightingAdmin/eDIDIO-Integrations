// Tests for the Twitch event -> eDIDIO frame mapper. Run: node --test
// (The tmi.js chat glue needs a live Twitch connection; this covers the mapping,
// which is the bot's real logic — decode each frame to assert the command.)

const test = require('node:test')
const assert = require('node:assert')

const builder = require('../src/edidio/messageBuilder')
const { maskForLine } = require('../src/edidio/lineTypes')
const pb = require('../src/edidio/eDS10_ProtocolBuffer_pb.js')
const { handleChat, handleReward, handleBits, parseChat, rankOf } = require('../src/mapper')

const CONFIG = require('../src/commands.example.json')

function decode(frame) {
	assert.strictEqual(frame[0], 0xcd)
	const len = (frame[1] << 8) | frame[2]
	assert.strictEqual(len, frame.length - 3)
	return pb.EdidioMessage.deserializeBinary(new Uint8Array(frame.slice(3)))
}

// --- chat parsing ---

test('parseChat splits prefix/name/args', () => {
	assert.deepStrictEqual(parseChat('!scene 3', '!'), { name: 'scene', args: ['3'] })
	assert.strictEqual(parseChat('hello', '!'), null)
})

test('rankOf from userstate', () => {
	assert.strictEqual(rankOf({ badges: { broadcaster: '1' } }), 3)
	assert.strictEqual(rankOf({ mod: true }), 2)
	assert.strictEqual(rankOf({ subscriber: true }), 1)
	assert.strictEqual(rankOf({}), 0)
})

// --- chat commands ---

test('!scene builds a broadcast-scene frame', () => {
	const r = handleChat(CONFIG, '!scene 3', {})
	const d = decode(r.frame).getDaliMessage()
	// GO TO SCENE 3 (0x10 + 3) broadcast to address 80
	assert.strictEqual(d.getAddress(), 80)
	assert.strictEqual(d.getCommand(), 0x10 + 3)
})

test('!light requires subscriber (denied for everyone)', () => {
	const r = handleChat(CONFIG, '!light 5 200', {})
	assert.ok(r.error && /subscriber/.test(r.error))
})

test('!light allowed for subscriber, builds arc level', () => {
	const r = handleChat(CONFIG, '!light 5 200', { subscriber: true })
	const d = decode(r.frame).getDaliMessage()
	assert.strictEqual(d.getAddress(), 5)
	assert.strictEqual(d.getArg(), 200)
})

test('!color requires moderator and builds DMX', () => {
	assert.ok(handleChat(CONFIG, '!color #FF0000', { subscriber: true }).error)
	const r = handleChat(CONFIG, '!color #FF0000', { mod: true })
	const d = decode(r.frame).getDmxMessage()
	assert.deepStrictEqual(d.getLevelList(), [255, 0, 0])
})

test('unknown command returns null', () => {
	assert.strictEqual(handleChat(CONFIG, '!nope', { mod: true }), null)
})

test('invalid arg returns a user error', () => {
	const r = handleChat(CONFIG, '!scene 99', {})
	assert.ok(r.error && /0-15/.test(r.error))
})

// --- channel-point rewards ---

test('reward title maps to action', () => {
	const r = handleReward(CONFIG, 'Red Alert')
	const d = decode(r.frame).getDmxMessage()
	assert.deepStrictEqual(d.getLevelList(), [255, 0, 0])
})

test('reward "Lights Out" recalls scene 0', () => {
	const r = handleReward(CONFIG, 'Lights Out')
	const d = decode(r.frame).getDaliMessage()
	assert.strictEqual(d.getArg(), 0)
})

test('unknown reward returns null', () => {
	assert.strictEqual(handleReward(CONFIG, 'Nonexistent'), null)
})

// --- bits ---

test('bits pick the highest matching tier', () => {
	assert.strictEqual(handleBits(CONFIG, 50), null) // below lowest tier
	const low = handleBits(CONFIG, 100)
	assert.ok(low.frame) // colour tier
	const high = handleBits(CONFIG, 5000)
	const d = decode(high.frame)
	assert.ok(d.getSpektraControl()) // sequence tier wins at 5000
})
