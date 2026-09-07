// Pure mapping from Telegram slash-commands to eDIDIO frames. No telegram lib /
// network here, so it is fully unit testable. The bot glue parses the message
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

// Default line for DALI commands (configurable via the command args).
const DEFAULT_LINE = 1
const DEFAULT_DMX_LINE = 2

// Parse "/scene 3" or "/scene 3@mybot" into { name, args }, or null.
function parseCommand(text) {
	if (typeof text !== 'string' || !text.startsWith('/')) return null
	const parts = text.trim().split(/\s+/)
	let name = parts.shift().slice(1).toLowerCase()
	const at = name.indexOf('@') // strip @botname suffix Telegram adds in groups
	if (at !== -1) name = name.slice(0, at)
	return { name, args: parts }
}

// Build a frame + reply for a parsed command. Returns { frame, reply } or
// { reply } (help/error, no frame) or null (unknown command).
function handleCommand(text) {
	const parsed = parseCommand(text)
	if (!parsed) return null
	const { name, args } = parsed

	try {
		switch (name) {
			case 'start':
			case 'help':
				return { reply: HELP }
			case 'scene': {
				const scene = int(args[0], 'scene', 0, 15)
				const line = int(args[1], 'line', 1, 4, DEFAULT_LINE)
				return { frame: builder.daliBroadcastScene({ scene, lineMask: maskForLine(line) }), reply: `💡 Recalled scene ${scene} on line ${line}` }
			}
			case 'on':
			case 'off': {
				const address = int(args[0], 'address', 0, 63)
				const line = int(args[1], 'line', 1, 4, DEFAULT_LINE)
				const command = name === 'on' ? builder.DALICommandType.DALI_MAX_LEVEL : builder.DALICommandType.DALI_OFF
				return { frame: builder.daliCommand({ address, command, lineMask: maskForLine(line) }), reply: `💡 Address ${address} ${name}` }
			}
			case 'level': {
				const address = int(args[0], 'address', 0, 63)
				const level = clampLevel(int(args[1], 'level', 0, 254))
				const line = int(args[2], 'line', 1, 4, DEFAULT_LINE)
				return { frame: builder.daliArcLevel({ address, level, lineMask: maskForLine(line) }), reply: `💡 Address ${address} → ${level}` }
			}
			case 'group': {
				const group = int(args[0], 'group', 0, 15)
				const level = clampLevel(int(args[1], 'level', 0, 254))
				const line = int(args[2], 'line', 1, 4, DEFAULT_LINE)
				return { frame: builder.daliGroupArcLevel({ group, level, lineMask: maskForLine(line) }), reply: `💡 Group ${group} → ${level}` }
			}
			case 'color': {
				const rgb = parseHex(args[0])
				if (!rgb) return { reply: '⚠️ Usage: /color #RRGGBB [line]' }
				const line = int(args[1], 'line', 1, 4, DEFAULT_DMX_LINE)
				const fixtures = Math.floor(512 / rgb.length)
				return { frame: builder.dmxColour({ zone: 0xff, universeMask: maskForLine(line), channel: 1, repeat: fixtures, levels: rgb }), reply: `🎨 Line ${line} → ${args[0]}` }
			}
			case 'seq': {
				const index = int(args[0], 'index', 0, 65535, 0)
				const zone = int(args[1], 'zone', 0, 255, 1)
				return { frame: builder.spektraControl({ type: builder.SpektraTargetType.SEQUENCE, zone, index, action: builder.SpektraActionType.START }), reply: `▶️ Sequence ${index} on zone ${zone}` }
			}
			default:
				return null
		}
	} catch (err) {
		return { reply: `⚠️ ${err.message}` }
	}
}

function int(value, name, lo, hi, dflt) {
	if (value === undefined || value === '') {
		if (dflt !== undefined) return dflt
		throw new Error(`missing ${name}`)
	}
	const n = Number(value)
	if (!Number.isInteger(n)) throw new Error(`${name} must be a whole number`)
	if (n < lo || n > hi) throw new Error(`${name} must be ${lo}-${hi}`)
	return n
}

const HELP = [
	'💡 eDIDIO lighting bot. Commands:',
	'/scene <0-15> [line] — recall a scene',
	'/on <addr> [line] · /off <addr> [line]',
	'/level <addr> <0-254> [line]',
	'/group <0-15> <0-254> [line]',
	'/color <#RRGGBB> [line] — DMX colour',
	'/seq <index> [zone] — start a SpektraPlus sequence',
].join('\n')

module.exports = { parseCommand, handleCommand, HELP }
