// Pure mapping from Twitch events (chat commands, channel-point rewards, bit
// cheers) to eDIDIO frames. No tmi.js / network here, so it is fully unit
// testable. The bot glue feeds parsed events in and sends the returned frame.

const builder = require('./edidio/messageBuilder')
const { maskForLine } = require('./edidio/lineTypes')

const PERMISSION_RANK = { everyone: 0, subscriber: 1, vip: 1, moderator: 2, broadcaster: 3 }

// Derive a numeric rank from a tmi.js userstate (or a simple role string).
function rankOf(user) {
	if (typeof user === 'string') return PERMISSION_RANK[user] ?? 0
	if (!user || typeof user !== 'object') return 0
	if (user.badges && user.badges.broadcaster) return 3
	if (user.mod || (user.badges && user.badges.moderator)) return 2
	if (user.subscriber || user.vip || (user.badges && (user.badges.vip || user.badges.subscriber))) return 1
	return 0
}

function clampLevel(v) {
	return Math.max(0, Math.min(254, Number(v)))
}

function parseHex(input) {
	const hex = String(input).replace(/^#/, '').trim()
	if (!/^[0-9a-fA-F]{6}$/.test(hex)) return null
	return [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)]
}

// Build an eDIDIO frame for an action spec ({action, line, ...}) with resolved
// values. Returns { frame, label } or throws Error(userMessage).
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
		default:
			throw new Error(`unknown action: ${spec.action}`)
	}
}

// --- Chat commands ---------------------------------------------------------

// Parse a chat line into { name, args } using the configured prefix, or null.
function parseChat(message, prefix) {
	if (typeof message !== 'string' || !message.startsWith(prefix)) return null
	const parts = message.slice(prefix.length).trim().split(/\s+/)
	const name = (parts.shift() || '').toLowerCase()
	if (!name) return null
	return { name, args: parts }
}

// Resolve a chat command against config + user rank.
// Returns { frame, label } | { error } | null (not a command / not allowed).
function handleChat(config, message, user) {
	const chat = config.chat || {}
	const parsed = parseChat(message, chat.prefix || '!')
	if (!parsed) return null
	const cmd = (chat.commands || {})[parsed.name]
	if (!cmd) return null

	const need = PERMISSION_RANK[cmd.permission] ?? 0
	if (rankOf(user) < need) return { error: `You need ${cmd.permission} to use !${parsed.name}.` }

	// Bind positional args named by argFrom into a spec.
	const spec = Object.assign({}, cmd)
	const argNames = Array.isArray(cmd.argFrom) ? cmd.argFrom : cmd.argFrom ? [cmd.argFrom] : []
	argNames.forEach((key, i) => {
		if (parsed.args[i] !== undefined) spec[key] = parsed.args[i]
	})

	try {
		return buildAction(spec)
	} catch (err) {
		return { error: err.message }
	}
}

// --- Channel-point rewards -------------------------------------------------

function handleReward(config, rewardTitle) {
	const spec = (config.rewards || {})[rewardTitle]
	if (!spec) return null
	try {
		return buildAction(spec)
	} catch (err) {
		return { error: err.message }
	}
}

// --- Bit cheers ------------------------------------------------------------

function handleBits(config, bits) {
	const tiers = (config.bits && config.bits.tiers) || []
	const eligible = tiers.filter((t) => Number(bits) >= Number(t.min)).sort((a, b) => b.min - a.min)
	if (eligible.length === 0) return null
	try {
		return buildAction(eligible[0])
	} catch (err) {
		return { error: err.message }
	}
}

module.exports = { buildAction, parseChat, handleChat, handleReward, handleBits, rankOf, PERMISSION_RANK }
