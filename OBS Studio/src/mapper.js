// Pure mapping from OBS events to eDIDIO frames. No obs-websocket / network
// here, so it is fully unit testable. The glue in index.js feeds OBS events in
// and sends the returned frame.

const builder = require('./edidio/messageBuilder')
const { maskForLine } = require('./edidio/lineTypes')

function clampLevel(v) {
	return Math.max(0, Math.min(254, Number(v)))
}

function parseHex(input) {
	const hex = String(input).replace(/^#/, '').trim()
	if (!/^[0-9a-fA-F]{6}$/.test(hex)) return null
	return [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)]
}

// Build an eDIDIO frame for an action spec. Returns { frame, label } or throws.
function buildAction(spec) {
	const line = Number(spec.line || 1)
	const mask = maskForLine(line)
	switch (spec.action) {
		case 'scene': {
			const scene = Number(spec.scene)
			if (!Number.isInteger(scene) || scene < 0 || scene > 15) throw new Error('scene must be 0-15')
			return { frame: builder.daliBroadcastScene({ scene, lineMask: mask }), label: `scene ${scene}` }
		}
		case 'level': {
			const address = Number(spec.address)
			const level = clampLevel(spec.level)
			if (!Number.isInteger(address) || address < 0 || address > 63) throw new Error('address must be 0-63')
			return { frame: builder.daliArcLevel({ address, level, lineMask: mask }), label: `addr ${address} → ${level}` }
		}
		case 'on':
		case 'off': {
			const address = Number(spec.address)
			if (!Number.isInteger(address) || address < 0 || address > 63) throw new Error('address must be 0-63')
			const command = spec.action === 'on' ? builder.DALICommandType.DALI_MAX_LEVEL : builder.DALICommandType.DALI_OFF
			return { frame: builder.daliCommand({ address, command, lineMask: mask }), label: `addr ${address} ${spec.action}` }
		}
		case 'color': {
			const rgb = parseHex(spec.hex)
			if (!rgb) throw new Error('colour must be #RRGGBB')
			const fixtures = Math.floor(512 / rgb.length)
			return { frame: builder.dmxColour({ zone: 0xff, universeMask: mask, channel: 1, repeat: fixtures, levels: rgb }), label: `colour ${spec.hex}` }
		}
		case 'spektra': {
			const zone = Number(spec.zone || 0)
			const index = Number(spec.index || 0)
			return {
				frame: builder.spektraControl({ type: builder.SpektraTargetType.SEQUENCE, zone, index, action: builder.SpektraActionType.START }),
				label: `sequence ${index} (zone ${zone})`,
			}
		}
		case 'spektraStop': {
			const zone = Number(spec.zone || 0)
			return { frame: builder.spektraStop({ zone }), label: `spektra stop (zone ${zone})` }
		}
		default:
			throw new Error(`unknown action: ${spec.action}`)
	}
}

// --- OBS event handlers (each returns { frame, label } | { error } | null) ---

// A scene became the current program scene.
function handleSceneChange(config, sceneName) {
	const spec = (config.scenes || {})[sceneName]
	if (!spec) return null
	try {
		return buildAction(spec)
	} catch (err) {
		return { error: err.message }
	}
}

// Stream started/stopped. `active` = true on start.
function handleStream(config, active) {
	const spec = (config.stream || {})[active ? 'onStart' : 'onStop']
	if (!spec) return null
	try {
		return buildAction(spec)
	} catch (err) {
		return { error: err.message }
	}
}

// Recording started/stopped. `active` = true on start.
function handleRecord(config, active) {
	const spec = (config.record || {})[active ? 'onStart' : 'onStop']
	if (!spec) return null
	try {
		return buildAction(spec)
	} catch (err) {
		return { error: err.message }
	}
}

module.exports = { buildAction, handleSceneChange, handleStream, handleRecord }
