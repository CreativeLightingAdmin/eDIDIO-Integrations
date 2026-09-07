// Verify the Stream Deck settings -> REST request mapping. Run: node --test
// (The Stream Deck WebSocket glue in app.js needs the Stream Deck app; this
// covers the request-building, which is the plugin's real logic.)

const test = require('node:test')
const assert = require('node:assert')
const { buildRequest } = require('../com.creativelighting.edidio.sdPlugin/request.js')

test('scene request', () => {
	const r = buildRequest({ gatewayUrl: 'http://gw:8080', command: 'scene', line: 1, scene: 3 })
	assert.strictEqual(r.url, 'http://gw:8080/api/v1/dali/scene')
	assert.strictEqual(r.method, 'POST')
	assert.deepStrictEqual(JSON.parse(r.body), { line: 1, scene: 3 })
})

test('scene on group', () => {
	const r = buildRequest({ gatewayUrl: 'http://gw:8080', command: 'scene', line: 1, scene: 3, group: 4 })
	assert.deepStrictEqual(JSON.parse(r.body), { line: 1, scene: 3, group: 4 })
})

test('level request with controller + api key', () => {
	const r = buildRequest({
		gatewayUrl: 'http://gw:8080/', apiKey: 'secret', controller: '192.168.1.50',
		command: 'level', line: 1, address: 5, level: 200,
	})
	assert.strictEqual(r.url, 'http://gw:8080/api/v1/dali/level')
	assert.strictEqual(r.headers['X-API-Key'], 'secret')
	assert.deepStrictEqual(JSON.parse(r.body), { controller: '192.168.1.50', line: 1, address: 5, level: 200 })
})

test('on/off command', () => {
	const r = buildRequest({ gatewayUrl: 'http://gw:8080', command: 'off', line: 1, address: 5 })
	assert.strictEqual(r.url, 'http://gw:8080/api/v1/dali/command')
	assert.deepStrictEqual(JSON.parse(r.body), { line: 1, address: 5, command: 'off' })
})

test('dmx color', () => {
	const r = buildRequest({ gatewayUrl: 'http://gw:8080', command: 'dmx_color', line: 2, hex: '#00FF00' })
	assert.strictEqual(r.url, 'http://gw:8080/api/v1/dmx/color')
	assert.deepStrictEqual(JSON.parse(r.body), { line: 2, hex: '#00FF00' })
})

test('spektra', () => {
	const r = buildRequest({ gatewayUrl: 'http://gw:8080', command: 'spektra', zone: 1, type: 'sequence', index: 0, action: 'start' })
	assert.strictEqual(r.url, 'http://gw:8080/api/v1/spektra')
	assert.deepStrictEqual(JSON.parse(r.body), { zone: 1, type: 'sequence', index: 0, action: 'start' })
})

test('unknown command throws', () => {
	assert.throws(() => buildRequest({ command: 'nope' }))
})

test('defaults gateway url', () => {
	const r = buildRequest({ command: 'scene', line: 1, scene: 0 })
	assert.strictEqual(r.url, 'http://localhost:8080/api/v1/dali/scene')
})
