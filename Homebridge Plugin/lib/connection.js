// TCP/TLS connection to an eDIDIO controller with keep-alive + auto-reconnect.
// Emits 'connect', 'disconnect', 'error'. Self-contained (uses the pure-JS
// encoder's KEEP_ALIVE frame). With enableEvents() it subscribes to the live
// event stream on every (re)connect and emits 'event' for each push.

const net = require('node:net')
const tls = require('node:tls')
const { EventEmitter } = require('node:events')
const frames = require('./edidio_frames.js')
const eventStream = require('./eventStream.js')

class ControllerConnection extends EventEmitter {
	constructor(ip, { port, useTLS = false, heartbeatMs = 7000 } = {}) {
		super()
		this.ip = ip
		this.useTLS = useTLS
		this.port = port || (useTLS ? 443 : 23)
		this.heartbeatMs = heartbeatMs
		this.socket = null
		this.connected = false
		this.shouldReconnect = false
		this.reconnectDelayMs = 2000
		this.heartbeatTimer = null
		this.reconnectTimer = null
		this.eventMask = null
		this._reader = new eventStream.FrameReader()
		this.on('error', () => {})
	}

	connect() {
		this.shouldReconnect = true
		return new Promise((resolve, reject) => {
			let settled = false
			const onConnected = () => {
				this.connected = true
				this.reconnectDelayMs = 2000
				this._startHeartbeat()
				this._subscribeEvents()
				this.emit('connect')
				if (!settled) {
					settled = true
					resolve()
				}
			}
			const socket = this.useTLS
				? tls.connect({ host: this.ip, port: this.port, rejectUnauthorized: false }, onConnected)
				: net.connect(this.port, this.ip, onConnected)
			this.socket = socket
			this._reader = new eventStream.FrameReader()
			socket.on('data', (chunk) => {
				for (const body of this._reader.push(chunk)) {
					const ev = eventStream.decodeFrame(body)
					if (ev) this.emit('event', ev)
				}
			})
			socket.on('error', (err) => {
				this.emit('error', err)
				if (!settled) {
					settled = true
					reject(err)
				}
			})
			socket.on('close', () => {
				const wasConnected = this.connected
				this.connected = false
				this._stopHeartbeat()
				if (wasConnected && this.shouldReconnect) this.emit('disconnect')
				this._scheduleReconnect()
			})
		})
	}

	disconnect() {
		this.shouldReconnect = false
		this._stopHeartbeat()
		if (this.reconnectTimer) {
			clearTimeout(this.reconnectTimer)
			this.reconnectTimer = null
		}
		if (this.socket) {
			this.socket.destroy()
			this.socket = null
		}
		this.connected = false
	}

	enableEvents(categories = ['dali', 'inputs', 'sensors', 'triggers']) {
		this.eventMask = eventStream.categoriesToMask(categories)
		this._subscribeEvents()
	}

	_subscribeEvents() {
		if (this.eventMask === null || !this.connected || !this.socket) return
		this.socket.write(Buffer.from(eventStream.buildSubscribe(this.eventMask)))
	}

	send(frame) {
		if (!this.connected || !this.socket) return Promise.resolve(false)
		return new Promise((resolve, reject) => {
			this.socket.write(Buffer.from(frame), (err) => (err ? reject(err) : resolve(true)))
		})
	}

	_startHeartbeat() {
		this._stopHeartbeat()
		this.heartbeatTimer = setInterval(() => {
			if (this.connected && this.socket) this.socket.write(Buffer.from(frames.KEEP_ALIVE))
		}, this.heartbeatMs)
	}

	_stopHeartbeat() {
		if (this.heartbeatTimer) {
			clearInterval(this.heartbeatTimer)
			this.heartbeatTimer = null
		}
	}

	_scheduleReconnect() {
		if (!this.shouldReconnect || this.reconnectTimer) return
		this.reconnectTimer = setTimeout(() => {
			this.reconnectTimer = null
			if (!this.shouldReconnect) return
			this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 2, 30000)
			this.connect().catch(() => {})
		}, this.reconnectDelayMs)
	}
}

module.exports = { ControllerConnection }
