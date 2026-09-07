// A single TCP/TLS connection to an eDIDIO controller, with automatic reconnect
// and a keep-alive heartbeat. Emits 'connect', 'disconnect' and 'error'.
//
// Self-contained (no external config module) so it can be embedded in the
// Node-RED config node. Ports default to 23 (plain TCP) / 443 (TLS).

const net = require('node:net');
const tls = require('node:tls');
const { EventEmitter } = require('node:events');
const { AYT_FRAME } = require('./messageBuilder');

const DEFAULT_TCP_PORT = 23;
const DEFAULT_TLS_PORT = 443;
const DEFAULT_HEARTBEAT_MS = 7000;

class ControllerConnection extends EventEmitter {
	// options: { port?, useTLS?, lineTypes?, heartbeatMs? }
	constructor(ip, { port, useTLS = false, lineTypes = null, heartbeatMs = DEFAULT_HEARTBEAT_MS } = {}) {
		super();
		this.ip = ip;
		this.useTLS = useTLS;
		this.lineTypes = lineTypes || null;
		this.port = port || (useTLS ? DEFAULT_TLS_PORT : DEFAULT_TCP_PORT);
		this.heartbeatMs = heartbeatMs;
		this.socket = null;
		this.connected = false;
		this.shouldReconnect = false;
		this.reconnectDelayMs = 2000;
		this.heartbeatTimer = null;
		this.reconnectTimer = null;
		// EventEmitter throws if 'error' has no listener; a default one guarantees
		// connection errors never crash the host process.
		this.on('error', () => {});
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
			// failed chain.
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
		}, this.heartbeatMs);
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
