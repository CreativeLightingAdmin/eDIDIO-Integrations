// Live feedback for Companion: button feedbacks + variables driven by the
// controller's event stream (firmware >= 1.4.0).
//
// StateStore folds decoded events (src/eventStream.js) into levels, Spektra
// playback and last input; it's pure so it can be unit tested without Companion.
// Levels reflect *every* change on the bus — wall panels, schedules, SpektraPlus —
// not just this module's own commands.

const es = require('./eventStream.js')

const SPEKTRA_START = 1
const SPEKTRA_STOP = 2

// eDIDIO address convention -> Companion variable id suffix.
function addressKey(address) {
	if (address === 80) return 'bc'
	if (address >= 64) return `g${address - 64}`
	return `a${address}`
}

function targetAddress(opt) {
	const id = Number(opt.id) || 0
	if (opt.target === 'broadcast') return 80
	if (opt.target === 'group') return 64 + id
	return id
}

class StateStore {
	constructor() {
		this.tracker = new es.LevelTracker()
		this.spektra = new Map() // zone -> { index, target } while playing
		this.lastInput = null
	}

	level(line, address) {
		const v = this.tracker.levels.get(`${line}:${address}`)
		return v === undefined ? undefined : v
	}

	// Apply one decoded event. Returns { variables: {id: value}, changed: bool }.
	apply(ev) {
		const variables = {}
		const change = es.daliChange(ev)
		if (change && !(change.level === null && change.command === 'scene')) {
			for (const t of this.tracker.apply(change)) {
				variables[`level_l${t.line}_${addressKey(t.address)}`] = t.level === null ? 'on' : t.level
			}
		} else if (ev.kind === 'spektra') {
			if (ev.action === SPEKTRA_START) this.spektra.set(ev.zone, { index: ev.index, target: ev.target })
			else if (ev.action === SPEKTRA_STOP) this.spektra.delete(ev.zone)
			const playing = this.spektra.get(ev.zone)
			variables[`spektra_z${ev.zone}`] = playing ? playing.index : ''
		} else if (ev.kind === 'input') {
			this.lastInput = ev.index
			variables.last_input = ev.index
		}
		return { variables, changed: Object.keys(variables).length > 0 }
	}

	isLevel(opt) {
		const level = this.level(Number(opt.line) || 1, targetAddress(opt))
		if (level === undefined) return false
		const on = level === null || level > 0
		switch (opt.state) {
			case 'on':
				return on
			case 'off':
				return !on
			case 'at_least':
				return level !== null && level >= (Number(opt.level) || 0)
			default:
				return false
		}
	}

	isPlaying(opt) {
		const playing = this.spektra.get(Number(opt.zone) || 0)
		if (!playing) return false
		return opt.index === '' || opt.index === undefined || Number(opt.index) === playing.index
	}
}

// Companion feedback definitions. `self.state` is a StateStore.
function getFeedbackDefinitions(self) {
	const style = { bgcolor: 0xffcc00, color: 0x000000 }
	return {
		dali_level: {
			type: 'boolean',
			name: 'DALI: Light state',
			description: 'Live state from the controller (needs firmware 1.4.0+).',
			defaultStyle: style,
			options: [
				{ type: 'number', label: 'Line (1-4)', id: 'line', default: 1, min: 1, max: 4 },
				{
					type: 'dropdown', label: 'Target', id: 'target', default: 'address',
					choices: [
						{ id: 'address', label: 'Address' },
						{ id: 'group', label: 'Group' },
						{ id: 'broadcast', label: 'Broadcast' },
					],
				},
				{ type: 'number', label: 'Address / group', id: 'id', default: 0, min: 0, max: 63 },
				{
					type: 'dropdown', label: 'When', id: 'state', default: 'on',
					choices: [
						{ id: 'on', label: 'On' },
						{ id: 'off', label: 'Off' },
						{ id: 'at_least', label: 'Level at least' },
					],
				},
				{ type: 'number', label: 'Level (0-254)', id: 'level', default: 127, min: 0, max: 254 },
			],
			callback: (fb) => self.state.isLevel(fb.options),
		},
		spektra_playing: {
			type: 'boolean',
			name: 'SpektraPlus: Playing',
			description: 'A sequence/theme is running in the zone (optionally a specific index).',
			defaultStyle: style,
			options: [
				{ type: 'number', label: 'Zone', id: 'zone', default: 0, min: 0, max: 255 },
				{ type: 'textinput', label: 'Index (blank = any)', id: 'index', default: '' },
			],
			callback: (fb) => self.state.isPlaying(fb.options),
		},
	}
}

module.exports = { StateStore, getFeedbackDefinitions, addressKey }
