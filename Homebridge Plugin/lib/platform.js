// Homebridge dynamic platform: DALI lights as HomeKit lightbulbs and stored
// scenes as momentary switches, sent straight to the controller over TCP/TLS.
// Live state from the controller's event stream (firmware 1.4.0+) keeps the Home
// app in sync with wall panels, schedules and other apps.

const { ControllerConnection } = require('./connection.js')
const es = require('./eventStream.js')
const map = require('./mapping.js')

const PLUGIN_NAME = 'homebridge-edidio'
const PLATFORM_NAME = 'EdidioPlatform'

class EdidioPlatform {
	constructor(log, config, api, { connectionFactory } = {}) {
		this.log = log
		this.config = config || {}
		this.api = api
		this.cached = new Map() // UUID -> PlatformAccessory restored from cache
		this.lights = new Map() // `${line}:${edidioAddress}` -> [{ light, service }]
		this.tracker = new es.LevelTracker()
		this._mid = 0
		this._connectionFactory =
			connectionFactory || ((host, opts) => new ControllerConnection(host, opts))

		if (!this.config.host) {
			log.error('eDIDIO: set "host" (controller IP) in the plugin config')
			return
		}
		api.on('didFinishLaunching', () => this.start())
		api.on('shutdown', () => this.conn && this.conn.disconnect())
	}

	// Homebridge hands back cached accessories before didFinishLaunching.
	configureAccessory(accessory) {
		this.cached.set(accessory.UUID, accessory)
	}

	start() {
		const entries = []
		for (const cfg of this.config.lights || []) entries.push(map.parseLight(cfg))
		for (const cfg of this.config.scenes || []) entries.push(map.parseScene(cfg))

		const wanted = new Set()
		for (const entry of entries) {
			const uuid = this.api.hap.uuid.generate(`${PLUGIN_NAME}:${this.config.host}:${entry.id}`)
			wanted.add(uuid)
			let accessory = this.cached.get(uuid)
			if (!accessory) {
				accessory = new this.api.platformAccessory(entry.name, uuid)
				this.api.registerPlatformAccessories(PLUGIN_NAME, PLATFORM_NAME, [accessory])
			}
			if (entry.kind === 'light') this._setupLight(accessory, entry)
			else this._setupScene(accessory, entry)
		}
		const stale = [...this.cached.values()].filter((a) => !wanted.has(a.UUID))
		if (stale.length) this.api.unregisterPlatformAccessories(PLUGIN_NAME, PLATFORM_NAME, stale)

		this._connect()
	}

	_connect() {
		this.conn = this._connectionFactory(this.config.host, {
			port: Number(this.config.port) || undefined,
			useTLS: !!this.config.useTLS,
		})
		this.conn.on('connect', () => this.log.info(`eDIDIO: connected to ${this.config.host}`))
		this.conn.on('disconnect', () => this.log.warn('eDIDIO: connection lost, reconnecting'))
		this.conn.on('error', (err) => this.log.debug(`eDIDIO: ${err.message || err}`))
		if (this.config.liveFeedback !== false) {
			this.conn.on('event', (ev) => this.onEvent(ev))
			this.conn.enableEvents(['dali'])
		}
		this.conn.connect().catch(() => {}) // keeps retrying in the background
	}

	_nextId() {
		this._mid = (this._mid + 1) & 0xffffff
		return this._mid
	}

	_send(frame) {
		if (!this.conn || !this.conn.connected) {
			this.log.warn('eDIDIO: not connected; command dropped')
			return
		}
		this.conn.send(frame).catch((err) => this.log.error(`eDIDIO: send failed: ${err.message}`))
	}

	_setupLight(accessory, light) {
		const { Service, Characteristic } = this.api.hap
		const service = accessory.getService(Service.Lightbulb) || accessory.addService(Service.Lightbulb, light.name)
		const state = { brightness: 100 }
		service.getCharacteristic(Characteristic.On).onSet((on) => {
			const level = on ? map.pctToArc(state.brightness) || map.DALI_ARC_LEVEL_MAX : 0
			this._send(map.levelFrame(light, level, this._nextId()))
		})
		service.getCharacteristic(Characteristic.Brightness).onSet((pct) => {
			state.brightness = pct
			this._send(map.levelFrame(light, map.pctToArc(pct), this._nextId()))
		})
		const key = `${light.line}:${light.edidioAddress}`
		if (!this.lights.has(key)) this.lights.set(key, [])
		this.lights.get(key).push({ light, service, state })
	}

	_setupScene(accessory, scene) {
		const { Service, Characteristic } = this.api.hap
		const service = accessory.getService(Service.Switch) || accessory.addService(Service.Switch, scene.name)
		const on = service.getCharacteristic(Characteristic.On)
		on.onSet((value) => {
			if (!value) return
			this._send(map.sceneFrame(scene, this._nextId()))
			// Momentary: flip back so it behaves like a "recall" button.
			setTimeout(() => on.updateValue(false), 1000).unref?.()
		})
	}

	// Reflect a DALI level seen on the bus (no command is sent).
	onEvent(ev) {
		const change = es.daliChange(ev)
		if (!change || (change.level === null && change.command === 'scene')) return
		const { Characteristic } = this.api.hap
		for (const t of this.tracker.apply(change)) {
			for (const { service, state } of this.lights.get(`${t.line}:${t.address}`) || []) {
				service.updateCharacteristic(Characteristic.On, t.level !== 0)
				if (t.level) {
					state.brightness = Math.max(1, map.arcToPct(t.level))
					service.updateCharacteristic(Characteristic.Brightness, state.brightness)
				}
			}
		}
	}
}

module.exports = { EdidioPlatform, PLUGIN_NAME, PLATFORM_NAME }
