// A single TCP connection to an eDIDIO controller, with automatic reconnect
// and a keep-alive heartbeat. Emits 'connect', 'disconnect' and 'error'.

const net = require('node:net');
const tls = require('node:tls');
const { EventEmitter } = require('node:events');
const { AYT_FRAME } = require('./messageBuilder');
const { config } = require('../config');

class ControllerConnection extends EventEmitter {
	// useTLS: connect over TLS (default port 443) instead of plain TCP (port 23).
	// lineTypes: array of LineType numbers per physical line (from discovery), or null.
	constructor(ip, { port, useTLS = false, lineTypes = null } = {}) {
		super();
		this.ip = ip;
		this.useTLS = useTLS;
		this.lineTypes = lineTypes || null;
		this.port = port || (useTLS ? config.controllerTlsPort : config.controllerPort);
		this.socket = null;
		this.connected = false;
		this.shouldReconnect = false;
		this.reconnectDelayMs = 2000;
		this.heartbeatTimer = null;
		this.reconnectTimer = null;
		// EventEmitter throws if 'error' is emitted with no listener. A default
		// listener guarantees connection errors are logged, never crash the bot,
		// and still allow additional listeners to be added.
		this.on('error', (err) => console.warn(`[controller ${this.ip}] ${err.message}`));
	}

	connect() {
		this.shouldReconnect = true;
		return new Promise((resolve, reject) => {
			let settled = false;

			const onConnected = () => {
				this.connected = true;
				this.reconnectDelayMs = 2000; // reset backoff on success
				this._startHeartbeat();
				this.emit('connect');
				if (!settled) {
					settled = true;
					resolve();
				}
			};

			// eDIDIO controllers present self-signed / legacy (RSA-1024) certs, so
			// like the SpektraPlus app we keep the socket up rather than reject on a
			// failed chain. (Trust pinning is a future enhancement.)
			const socket = this.useTLS
				? tls.connect({ host: this.ip, port: this.port, rejectUnauthorized: false }, onConnected)
				: net.connect(this.port, this.ip, onConnected);
			this.socket = socket;

			socket.on('error', (err) => {
				this.emit('error', err);
				if (!settled) {
					settled = true;
					reject(err);
				}
			});

			socket.on('close', () => {
				const wasConnected = this.connected;
				this.connected = false;
				this._stopHeartbeat();
				// Only signal an *unexpected* drop. An intentional disconnect() sets
				// shouldReconnect = false first, so it won't fire a false alarm.
				if (wasConnected && this.shouldReconnect) this.emit('disconnect');
				this._scheduleReconnect();
			});
		});
	}

	// Cleanly close and stop reconnecting.
	disconnect() {
		this.shouldReconnect = false;
		this._stopHeartbeat();
		if (this.reconnectTimer) {
			clearTimeout(this.reconnectTimer);
			this.reconnectTimer = null;
		}
		if (this.socket) {
			this.socket.destroy();
			this.socket = null;
		}
		this.connected = false;
	}

	// Write a framed message. Resolves true if sent, false if not connected.
	send(frame) {
		if (!this.connected || !this.socket) return Promise.resolve(false);
		return new Promise((resolve, reject) => {
			this.socket.write(Buffer.from(frame), (err) => {
				if (err) reject(err);
				else resolve(true);
			});
		});
	}

	_startHeartbeat() {
		this._stopHeartbeat();
		this.heartbeatTimer = setInterval(() => {
			if (this.connected && this.socket) {
				this.socket.write(Buffer.from(AYT_FRAME));
			}
		}, config.heartbeatIntervalMs);
	}

	_stopHeartbeat() {
		if (this.heartbeatTimer) {
			clearInterval(this.heartbeatTimer);
			this.heartbeatTimer = null;
		}
	}

	_scheduleReconnect() {
		if (!this.shouldReconnect || this.reconnectTimer) return;
		const delay = this.reconnectDelayMs;
		this.reconnectTimer = setTimeout(() => {
			this.reconnectTimer = null;
			if (!this.shouldReconnect) return;
			// Exponential backoff, capped at 30s.
			this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 2, 30000);
			this.connect().catch(() => {
				/* error already emitted; close handler reschedules */
			});
		}, delay);
	}
}

module.exports = { ControllerConnection };
