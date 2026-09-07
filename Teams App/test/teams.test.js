const test = require('node:test')
const assert = require('node:assert')
const crypto = require('node:crypto')

const { handleCommand } = require('../src/mapper')
const { computeAuth, verify } = require('../src/verify')
const { extractCommand } = require('../src/extract')

const OPTS = { gatewayUrl: 'http://gw:8080', apiKey: 'secret', controller: '192.168.1.50' }

// --- mapper (shared with Slack; spot-check a few) ---

test('mapper: scene -> REST request', () => {
	const r = handleCommand('scene 3', OPTS)
	assert.strictEqual(r.request.url, 'http://gw:8080/api/v1/dali/scene')
	assert.deepStrictEqual(JSON.parse(r.request.body), { controller: '192.168.1.50', line: 1, scene: 3 })
})

test('mapper: help has no request', () => {
	assert.strictEqual(handleCommand('help', OPTS).request, undefined)
})

// --- extract command from a Teams activity ---

test('extract strips <at> mention', () => {
	assert.strictEqual(extractCommand({ text: '<at>eDIDIO</at> scene 3' }, 'eDIDIO'), 'scene 3')
})

test('extract strips leading bot name word', () => {
	assert.strictEqual(extractCommand({ text: 'eDIDIO on 5' }, 'eDIDIO'), 'on 5')
})

test('extract handles plain text', () => {
	assert.strictEqual(extractCommand({ text: 'level 5 200' }, 'eDIDIO'), 'level 5 200')
})

test('extract empty', () => {
	assert.strictEqual(extractCommand({ text: '<at>eDIDIO</at>' }, 'eDIDIO'), '')
})

// --- HMAC verification ---

const SECRET = Buffer.from('super-secret-key').toString('base64')

test('verify accepts a correctly signed body', () => {
	const body = Buffer.from(JSON.stringify({ type: 'message', text: 'eDIDIO scene 3' }))
	const auth = computeAuth(body, SECRET)
	assert.strictEqual(verify(body, SECRET, auth), true)
})

test('verify rejects a bad signature', () => {
	const body = Buffer.from('{"text":"x"}')
	assert.strictEqual(verify(body, SECRET, 'HMAC wrongwrongwrong'), false)
})

test('verify rejects a tampered body', () => {
	const body = Buffer.from('{"text":"scene 3"}')
	const auth = computeAuth(body, SECRET)
	const tampered = Buffer.from('{"text":"scene 9"}')
	assert.strictEqual(verify(tampered, SECRET, auth), false)
})

test('verify computeAuth matches Teams format (HMAC <base64>)', () => {
	const body = Buffer.from('hello')
	const key = Buffer.from(SECRET, 'base64')
	const expected = 'HMAC ' + crypto.createHmac('sha256', key).update(body).digest('base64')
	assert.strictEqual(computeAuth(body, SECRET), expected)
})

test('verify disabled when no secret (dev)', () => {
	assert.strictEqual(verify(Buffer.from('x'), '', null), true)
})
