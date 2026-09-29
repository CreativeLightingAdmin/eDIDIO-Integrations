// Bitfocus Companion module for eDIDIO lighting control.
//
// Sends byte-verified eDIDIO frames directly over TCP/TLS (no gateway needed) —
// the frame encoding is the same one used across all the eDIDIO integrations.
// Live feedbacks/variables come from the controller's event stream (fw 1.4.0+).

const { InstanceBase, InstanceStatus, runEntrypoint } = require('@companion-module/base')
const { ControllerConnection } = require('./src/connection.js')
const { buildFrame, getActionDefinitions } = require('./src/actions.js')
const { StateStore, getFeedbackDefinitions } = require('./src/feedbacks.js')

class EdidioInstance extends InstanceBase {
	async init(config) {
		this.config = config
		this._mid = 0
		this.state = new StateStore()
		this._variables = new Map() // id -> definition, grown as targets are seen
		this.setActionDefinitions(getActionDefinitions(this))
		this.setFeedbackDefinitions(getFeedbackDefinitions(this))
		this._defineVariable('last_input', 'Last input pressed')
		await this._connect()
	}

	async destroy() {
		if (this.conn) this.conn.disconnect()
	}

	async configUpdated(config) {
		this.config = config
		if (this.conn) this.conn.disconnect()
		await this._connect()
	}

	getConfigFields() {
		return [
			{ type: 'textinput', id: 'host', label: 'Controller IP', width: 8, required: true },
			{ type: 'number', id: 'port', label: 'Port (23 TCP / 443 TLS)', width: 4, default: 23, min: 1, max: 65535 },
			{ type: 'checkbox', id: 'useTLS', label: 'Use TLS', width: 4, default: false },
			{ type: 'checkbox', id: 'liveFeedback', label: 'Live feedback (firmware 1.4.0+)', width: 4, default: true },
		]
	}

	async _connect() {
		if (!this.config || !this.config.host) {
			this.updateStatus(InstanceStatus.BadConfig, 'Set the controller IP')
			return
		}
		this.updateStatus(InstanceStatus.Connecting)
		this.conn = new ControllerConnection(this.config.host, {
			port: Number(this.config.port) || undefined,
			useTLS: !!this.config.useTLS,
		})
		this.conn.on('connect', () => this.updateStatus(InstanceStatus.Ok))
		this.conn.on('disconnect', () => this.updateStatus(InstanceStatus.Disconnected))
		this.conn.on('error', (err) => this.updateStatus(InstanceStatus.ConnectionFailure, String(err.message || err)))
		if (this.config.liveFeedback !== false) {
			this.conn.on('event', (ev) => this._onEvent(ev))
			this.conn.enableEvents()
		}
		try {
			await this.conn.connect()
		} catch (err) {
			this.updateStatus(InstanceStatus.ConnectionFailure, String(err.message || err))
		}
	}

	_defineVariable(id, name) {
		if (this._variables.has(id)) return false
		this._variables.set(id, { variableId: id, name })
		this.setVariableDefinitions([...this._variables.values()])
		return true
	}

	_onEvent(ev) {
		const { variables, changed } = this.state.apply(ev)
		if (!changed) return
		for (const id of Object.keys(variables)) {
			this._defineVariable(id, id.startsWith('spektra_') ? `Spektra playing (${id})` : `Level ${id}`)
		}
		this.setVariableValues(variables)
		this.checkFeedbacks('dali_level', 'spektra_playing')
	}

	_nextId() {
		this._mid = (this._mid + 1) & 0xffffff
		return this._mid
	}

	// Called by action callbacks: build the frame and send it.
	async dispatch(actionId, options) {
		let frame
		try {
			frame = buildFrame(actionId, options, this._nextId())
		} catch (err) {
			this.log('error', `Build ${actionId} failed: ${err.message}`)
			return
		}
		if (!this.conn || !this.conn.connected) {
			this.log('warn', 'Not connected to controller; command dropped')
			return
		}
		try {
			await this.conn.send(frame)
		} catch (err) {
			this.log('error', `Send failed: ${err.message}`)
		}
	}
}

runEntrypoint(EdidioInstance, [])
