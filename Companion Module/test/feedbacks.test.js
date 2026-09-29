// Live feedback tests: decoded events -> StateStore -> feedback/variable values.
// Frames are fed through the real decoder (src/eventStream.js) as the socket would.

const test = require('node:test')
const assert = require('node:assert')
const es = require('../src/eventStream.js')
const { StateStore, getFeedbackDefinitions } = require('../src/feedbacks.js')

const dali = (frame, line = 0) => ({ kind: 'dali', frame, frame_type: 1, line })

test('DALI frames update level variables and feedbacks', () => {
	const s = new StateStore()
	const r = s.apply(dali(0x0ac8)) // line 1 addr 5 arc 200
	assert.deepStrictEqual(r.variables, { level_l1_a5: 200 })
	assert.strictEqual(s.isLevel({ line: 1, target: 'address', id: 5, state: 'on' }), true)
	assert.strictEqual(s.isLevel({ line: 1, target: 'address', id: 5, state: 'at_least', level: 201 }), false)
	s.apply(dali(0xff00)) // broadcast OFF
	assert.strictEqual(s.isLevel({ line: 1, target: 'address', id: 5, state: 'off' }), true)
	assert.strictEqual(s.isLevel({ line: 1, target: 'broadcast', state: 'off' }), true)
	// Unknown target: neither on nor off.
	assert.strictEqual(s.isLevel({ line: 2, target: 'group', id: 3, state: 'off' }), false)
})

test('group variable naming and scene frames are ignored', () => {
	const s = new StateStore()
	assert.deepStrictEqual(s.apply(dali(0x8680)).variables, { level_l1_g3: 128 })
	assert.strictEqual(s.apply(dali(0x0b13)).changed, false) // GO TO SCENE: level unknown
})

test('Spektra playback and inputs', () => {
	const s = new StateStore()
	assert.deepStrictEqual(s.apply({ kind: 'spektra', zone: 1, action: 1, target: 1, index: 4 }).variables, { spektra_z1: 4 })
	assert.strictEqual(s.isPlaying({ zone: 1, index: '' }), true)
	assert.strictEqual(s.isPlaying({ zone: 1, index: 3 }), false)
	s.apply({ kind: 'spektra', zone: 1, action: 2, target: 1, index: 4 })
	assert.strictEqual(s.isPlaying({ zone: 1, index: '' }), false)
	assert.deepStrictEqual(s.apply({ kind: 'input', index: 7 }).variables, { last_input: 7 })
})

test('end to end from wire bytes (Python-engine fixture)', () => {
	const r = new es.FrameReader()
	const body = Buffer.from('ea040e280540039201070801180128c815', 'hex') // line 1 (0-based) addr 5 arc 200
	const [frame] = r.push(Buffer.concat([Buffer.from([0xcd, 0, body.length]), body]))
	const s = new StateStore()
	assert.deepStrictEqual(s.apply(es.decodeFrame(frame)).variables, { level_l2_a5: 200 })
})

test('feedback definitions call into the store', () => {
	const self = { state: new StateStore() }
	const defs = getFeedbackDefinitions(self)
	self.state.apply(dali(0x0ac8))
	assert.strictEqual(defs.dali_level.callback({ options: { line: 1, target: 'address', id: 5, state: 'on' } }), true)
	assert.strictEqual(defs.spektra_playing.callback({ options: { zone: 0, index: '' } }), false)
})
