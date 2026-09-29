// Platform tests against a fake Homebridge API + fake controller connection:
// HomeKit writes -> byte-verified frames, bus events -> characteristic updates.

const test = require('node:test')
const assert = require('node:assert')
const { EventEmitter } = require('node:events')
const frames = require('../lib/edidio_frames.js')
const map = require('../lib/mapping.js')
const { EdidioPlatform } = require('../lib/platform.js')
const plugin = require('../index.js')

const hex = (b) => Buffer.from(b).toString('hex')

// --- fakes -------------------------------------------------------------------

class FakeCharacteristic {
	constructor() {
		this.value = undefined
		this.setter = null
	}
	onSet(fn) {
		this.setter = fn
		return this
	}
	updateValue(v) {
		this.value = v
	}
}

class FakeService {
	constructor(type, name) {
		this.type = type
		this.name = name
		this.chars = new Map()
	}
	getCharacteristic(c) {
		if (!this.chars.has(c)) this.chars.set(c, new FakeCharacteristic())
		return this.chars.get(c)
	}
	updateCharacteristic(c, v) {
		this.getCharacteristic(c).value = v
		return this
	}
}

class FakeAccessory {
	constructor(name, uuid) {
		this.displayName = name
		this.UUID = uuid
		this.services = []
	}
	getService(type) {
		return this.services.find((s) => s.type === type)
	}
	addService(type, name) {
		const s = new FakeService(type, name)
		this.services.push(s)
		return s
	}
}

function fakeApi() {
	const api = new EventEmitter()
	api.hap = {
		uuid: { generate: (s) => `uuid(${s})` },
		Service: { Lightbulb: 'Lightbulb', Switch: 'Switch' },
		Characteristic: { On: 'On', Brightness: 'Brightness' },
	}
	api.platformAccessory = FakeAccessory
	api.registered = []
	api.unregistered = []
	api.registerPlatformAccessories = (p, n, list) => api.registered.push(...list)
	api.unregisterPlatformAccessories = (p, n, list) => api.unregistered.push(...list)
	api.registerPlatform = (...args) => (api.platform = args)
	return api
}

class FakeConnection extends EventEmitter {
	constructor() {
		super()
		this.connected = true
		this.sent = []
		this.eventsEnabled = null
	}
	connect() {
		return Promise.resolve()
	}
	disconnect() {}
	enableEvents(c) {
		this.eventsEnabled = c
	}
	send(f) {
		this.sent.push(hex(f))
		return Promise.resolve(true)
	}
}

const log = { info() {}, warn() {}, error() {}, debug() {} }
const CONFIG = {
	host: '10.0.0.1',
	lights: [
		{ name: 'Kitchen', line: 1, address: 5 },
		{ name: 'Living', line: 1, group: 2 },
	],
	scenes: [{ name: 'Movie', line: 1, scene: 3 }],
}

function launch(config = CONFIG, cached = []) {
	const api = fakeApi()
	const conn = new FakeConnection()
	const p = new EdidioPlatform(log, config, api, { connectionFactory: () => conn })
	for (const a of cached) p.configureAccessory(a)
	api.emit('didFinishLaunching')
	const byName = Object.fromEntries(
		[...cached, ...api.registered].map((a) => [a.displayName, a.services[0]]),
	)
	return { api, conn, p, byName }
}

// --- tests -------------------------------------------------------------------

test('index registers the dynamic platform', () => {
	const api = fakeApi()
	plugin(api)
	assert.deepStrictEqual(api.platform.slice(0, 2), ['homebridge-edidio', 'EdidioPlatform'])
})

test('mapping validates config and converts levels', () => {
	assert.throws(() => map.parseLight({ name: 'x', line: 1 }), /exactly one/)
	assert.throws(() => map.parseLight({ name: 'x', line: 5, address: 1 }), /line/)
	assert.strictEqual(map.parseLight({ name: 'g', group: 2 }).edidioAddress, 66)
	assert.strictEqual(map.pctToArc(50), 127)
	assert.strictEqual(map.arcToPct(254), 100)
})

test('HomeKit writes send byte-verified frames', () => {
	const { conn, byName } = launch()
	byName.Kitchen.getCharacteristic('Brightness').setter(50)
	assert.strictEqual(conn.sent.at(-1), hex(frames.daliArcLevel(1, frames.lineMask(1), 5, 127)))
	byName.Living.getCharacteristic('On').setter(false)
	assert.strictEqual(conn.sent.at(-1), hex(frames.daliGroupArcLevel(2, frames.lineMask(1), 2, 0)))
	byName.Movie.getCharacteristic('On').setter(true)
	assert.strictEqual(conn.sent.at(-1), hex(frames.daliBroadcastScene(3, frames.lineMask(1), 3)))
	assert.deepStrictEqual(conn.eventsEnabled, ['dali'])
})

test('bus events update HomeKit without sending commands', () => {
	const { conn, p, byName } = launch()
	p.onEvent({ kind: 'dali', line: 0, frame_type: 1, frame: 0x0a7f }) // addr 5 arc 127
	assert.strictEqual(byName.Kitchen.getCharacteristic('On').value, true)
	assert.strictEqual(byName.Kitchen.getCharacteristic('Brightness').value, 50)
	p.onEvent({ kind: 'dali', line: 0, frame_type: 1, frame: 0xff00 }) // broadcast OFF
	assert.strictEqual(byName.Kitchen.getCharacteristic('On').value, false)
	p.onEvent({ kind: 'dali', line: 0, frame_type: 1, frame: 0x84fe }) // group 2 arc 254
	assert.strictEqual(byName.Living.getCharacteristic('Brightness').value, 100)
	assert.deepStrictEqual(conn.sent, [])
	// On after feedback restores the observed brightness.
	byName.Kitchen.getCharacteristic('On').setter(true)
	assert.strictEqual(conn.sent.at(-1), hex(frames.daliArcLevel(1, frames.lineMask(1), 5, 127)))
})

test('cached accessories are reused and removed ones unregistered', () => {
	const api = fakeApi()
	const keep = new FakeAccessory('Kitchen', api.hap.uuid.generate('homebridge-edidio:10.0.0.1:light:1:5'))
	const gone = new FakeAccessory('Old', 'uuid(old)')
	const { api: a2 } = launch({ ...CONFIG, lights: [CONFIG.lights[0]], scenes: [] }, [keep, gone])
	assert.deepStrictEqual(a2.registered, [])
	assert.deepStrictEqual(a2.unregistered.map((x) => x.displayName), ['Old'])
	assert.ok(keep.getService('Lightbulb'))
})
