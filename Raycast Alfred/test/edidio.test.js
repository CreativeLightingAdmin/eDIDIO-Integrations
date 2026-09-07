const test = require('node:test')
const assert = require('node:assert')
const { buildRequest } = require('../lib/edidio')

const ENV = { gateway: 'http://gw:8080', apiKey: 'secret', controller: '192.168.1.50' }

test('scene', () => {
	const r = buildRequest(['scene', '3'], ENV)
	assert.strictEqual(r.url, 'http://gw:8080/api/v1/dali/scene')
	assert.strictEqual(r.headers['X-API-Key'], 'secret')
	assert.deepStrictEqual(JSON.parse(r.body), { controller: '192.168.1.50', line: 1, scene: 3 })
})

test('level', () => {
	const r = buildRequest(['level', '5', '200'], ENV)
	assert.strictEqual(r.url, 'http://gw:8080/api/v1/dali/level')
	assert.deepStrictEqual(JSON.parse(r.body), { controller: '192.168.1.50', line: 1, address: 5, level: 200 })
})

test('group', () => {
	const r = buildRequest(['group', '0', '128'], ENV)
	assert.deepStrictEqual(JSON.parse(r.body), { controller: '192.168.1.50', line: 1, group: 0, level: 128 })
})

test('on/off', () => {
	assert.deepStrictEqual(JSON.parse(buildRequest(['on', '5'], ENV).body).command, 'on')
	assert.deepStrictEqual(JSON.parse(buildRequest(['off', '5'], ENV).body).command, 'off')
})

test('color uses dmx line default 2', () => {
	const r = buildRequest(['color', '#FF0000'], ENV)
	assert.strictEqual(r.url, 'http://gw:8080/api/v1/dmx/color')
	assert.deepStrictEqual(JSON.parse(r.body), { controller: '192.168.1.50', line: 2, hex: '#FF0000' })
})

test('color invalid throws', () => {
	assert.throws(() => buildRequest(['color', 'nope'], ENV))
})

test('seq', () => {
	const r = buildRequest(['seq', '0', '1'], ENV)
	assert.deepStrictEqual(JSON.parse(r.body), { controller: '192.168.1.50', zone: 1, type: 'sequence', index: 0, action: 'start' })
})

test('no controller / key omits them', () => {
	const r = buildRequest(['scene', '3'], { gateway: 'http://gw:8080' })
	assert.strictEqual(r.headers['X-API-Key'], undefined)
	assert.deepStrictEqual(JSON.parse(r.body), { line: 1, scene: 3 })
})

test('unknown command throws', () => {
	assert.throws(() => buildRequest(['teleport'], ENV))
})

test('EDIDIO_LINE overrides line', () => {
	const r = buildRequest(['scene', '3'], Object.assign({ line: '4' }, ENV))
	assert.strictEqual(JSON.parse(r.body).line, 4)
})
