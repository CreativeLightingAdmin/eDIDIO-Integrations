const test = require('node:test')
const assert = require('node:assert')
const { handleCommand } = require('../src/mapper')

const OPTS = { gatewayUrl: 'http://gw:8080', apiKey: 'secret', controller: '192.168.1.50' }

test('help / empty', () => {
	assert.ok(handleCommand('', OPTS).reply.includes('eDIDIO'))
	assert.ok(handleCommand('help', OPTS).reply.includes('scene'))
})

test('scene', () => {
	const r = handleCommand('scene 3', OPTS)
	assert.strictEqual(r.request.url, 'http://gw:8080/api/v1/dali/scene')
	assert.strictEqual(r.request.headers['X-API-Key'], 'secret')
	assert.deepStrictEqual(JSON.parse(r.request.body), { controller: '192.168.1.50', line: 1, scene: 3 })
})

test('level', () => {
	const r = handleCommand('level 5 200', OPTS)
	assert.strictEqual(r.request.url, 'http://gw:8080/api/v1/dali/level')
	assert.deepStrictEqual(JSON.parse(r.request.body), { controller: '192.168.1.50', line: 1, address: 5, level: 200 })
})

test('group', () => {
	const r = handleCommand('group 0 128', OPTS)
	assert.strictEqual(r.request.url, 'http://gw:8080/api/v1/dali/group/level')
	assert.deepStrictEqual(JSON.parse(r.request.body), { controller: '192.168.1.50', line: 1, group: 0, level: 128 })
})

test('on/off', () => {
	assert.deepStrictEqual(JSON.parse(handleCommand('on 5', OPTS).request.body), { controller: '192.168.1.50', line: 1, address: 5, command: 'on' })
	assert.deepStrictEqual(JSON.parse(handleCommand('off 5', OPTS).request.body).command, 'off')
})

test('color', () => {
	const r = handleCommand('color #FF0000', OPTS)
	assert.strictEqual(r.request.url, 'http://gw:8080/api/v1/dmx/color')
	assert.deepStrictEqual(JSON.parse(r.request.body), { controller: '192.168.1.50', line: 2, hex: '#FF0000' })
})

test('color invalid -> usage', () => {
	assert.ok(handleCommand('color nope', OPTS).reply.includes('Usage'))
})

test('seq', () => {
	const r = handleCommand('seq 0 1', OPTS)
	assert.deepStrictEqual(JSON.parse(r.request.body), { controller: '192.168.1.50', zone: 1, type: 'sequence', index: 0, action: 'start' })
})

test('no controller / no api key omits them', () => {
	const r = handleCommand('scene 3', { gatewayUrl: 'http://gw:8080' })
	assert.strictEqual(r.request.headers['X-API-Key'], undefined)
	assert.deepStrictEqual(JSON.parse(r.request.body), { line: 1, scene: 3 })
})

test('unknown command', () => {
	assert.ok(handleCommand('teleport', OPTS).reply.includes('Unknown'))
})

test('out of range', () => {
	assert.ok(handleCommand('scene 99', OPTS).reply.includes('0-15'))
})
