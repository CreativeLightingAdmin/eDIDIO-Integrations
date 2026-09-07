// eDIDIO action definitions for Bitfocus Companion, plus `buildFrame` — the pure
// mapping from an action + options to an eDIDIO frame (byte-verified encoder).
// buildFrame is kept side-effect-free so it can be unit tested without Companion.

const frames = require('./edidio_frames.js')

function num(v, d = 0) {
	const n = Number(v)
	return Number.isNaN(n) ? d : n
}

function parseHex(input) {
	const hex = String(input).replace(/^#/, '').trim()
	if (!/^[0-9a-fA-F]{6}$/.test(hex)) throw new Error('colour must be #RRGGBB')
	return [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)]
}

const SPEKTRA_TARGET = { sequence: frames.SPEKTRA_SEQUENCE, theme: frames.SPEKTRA_THEME, static: frames.SPEKTRA_STATIC }
const SPEKTRA_ACTION = { start: frames.SPEKTRA_START, stop: frames.SPEKTRA_STOP, pause: frames.SPEKTRA_PAUSE }

// Turn an action id + options into a framed message (Uint8Array), or throw.
function buildFrame(actionId, opt, mid) {
	const lm = frames.lineMask(num(opt.line, 1))
	switch (actionId) {
		case 'set_level':
			return frames.daliArcLevel(mid, lm, num(opt.address), num(opt.level))
		case 'set_group_level':
			return frames.daliGroupArcLevel(mid, lm, num(opt.group), num(opt.level))
		case 'dali_command':
			return frames.daliCommand(mid, lm, num(opt.address), opt.command)
		case 'recall_scene': {
			const g = opt.group
			if (g === '' || g === undefined || g === null) {
				return frames.daliBroadcastScene(mid, lm, num(opt.scene))
			}
			return frames.daliSceneOnGroup(mid, lm, num(g), num(opt.scene))
		}
		case 'dmx_color': {
			const rgb = parseHex(opt.hex)
			return frames.dmxLevel(mid, 0xff, lm, 1, Math.floor(512 / rgb.length), rgb, 0)
		}
		case 'spektra': {
			const t = SPEKTRA_TARGET[String(opt.type).toLowerCase()]
			const a = SPEKTRA_ACTION[String(opt.action).toLowerCase()]
			if (t === undefined) throw new Error('unknown Spektra type: ' + opt.type)
			if (a === undefined) throw new Error('unknown Spektra action: ' + opt.action)
			return frames.spektraControl(mid, t, num(opt.zone), num(opt.index), a)
		}
		case 'spektra_stop':
			return frames.spektraStop(mid, num(opt.zone))
		default:
			throw new Error('unknown action: ' + actionId)
	}
}

// Companion action definitions. `self` is the module instance (provides
// self.dispatch(actionId, options)).
function getActionDefinitions(self) {
	const line = { type: 'number', label: 'Line (1-4)', id: 'line', default: 1, min: 1, max: 4 }
	const run = (id) => ({ options }) => self.dispatch(id, options)

	return {
		set_level: {
			name: 'DALI: Set level',
			options: [line,
				{ type: 'number', label: 'Address (0-63)', id: 'address', default: 0, min: 0, max: 63 },
				{ type: 'number', label: 'Level (0-254)', id: 'level', default: 254, min: 0, max: 254 }],
			callback: run('set_level'),
		},
		set_group_level: {
			name: 'DALI: Set group level',
			options: [line,
				{ type: 'number', label: 'Group (0-15)', id: 'group', default: 0, min: 0, max: 15 },
				{ type: 'number', label: 'Level (0-254)', id: 'level', default: 254, min: 0, max: 254 }],
			callback: run('set_group_level'),
		},
		dali_command: {
			name: 'DALI: Command',
			options: [line,
				{ type: 'number', label: 'Address (0-63)', id: 'address', default: 0, min: 0, max: 63 },
				{ type: 'dropdown', label: 'Command', id: 'command', default: 'off',
					choices: ['off', 'on', 'max', 'min', 'fade_up', 'fade_down', 'step_up', 'step_down', 'recall_last', 'identify'].map((c) => ({ id: c, label: c })) }],
			callback: run('dali_command'),
		},
		recall_scene: {
			name: 'DALI: Recall scene',
			options: [line,
				{ type: 'number', label: 'Scene (0-15)', id: 'scene', default: 0, min: 0, max: 15 },
				{ type: 'textinput', label: 'Group (blank = broadcast)', id: 'group', default: '' }],
			callback: run('recall_scene'),
		},
		dmx_color: {
			name: 'DMX: Colour',
			options: [line, { type: 'textinput', label: 'Colour #RRGGBB', id: 'hex', default: '#FF0000' }],
			callback: run('dmx_color'),
		},
		spektra: {
			name: 'SpektraPlus: Control',
			options: [
				{ type: 'number', label: 'Zone', id: 'zone', default: 0, min: 0, max: 255 },
				{ type: 'dropdown', label: 'Type', id: 'type', default: 'sequence', choices: ['sequence', 'theme', 'static'].map((c) => ({ id: c, label: c })) },
				{ type: 'number', label: 'Index', id: 'index', default: 0, min: 0, max: 65535 },
				{ type: 'dropdown', label: 'Action', id: 'action', default: 'start', choices: ['start', 'stop', 'pause'].map((c) => ({ id: c, label: c })) }],
			callback: run('spektra'),
		},
		spektra_stop: {
			name: 'SpektraPlus: Stop (and off)',
			options: [{ type: 'number', label: 'Zone', id: 'zone', default: 0, min: 0, max: 255 }],
			callback: run('spektra_stop'),
		},
	}
}

module.exports = { buildFrame, getActionDefinitions }
