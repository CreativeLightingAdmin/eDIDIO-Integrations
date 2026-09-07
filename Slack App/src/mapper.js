// Pure mapping from a Slack slash-command text to an eDIDIO REST Gateway request.
// No Express / network here, so it is fully unit testable. The server parses the
// Slack payload and performs the returned request.

function num(v, d) {
	const n = Number(v)
	return Number.isNaN(n) ? d : n
}

// text is everything after the slash command, e.g. "scene 3" or "level 5 200".
// Returns { request: {method,url,headers,body}, reply } or { reply } (help/error).
function handleCommand(text, opts) {
	const base = String(opts.gatewayUrl || 'http://localhost:8080').replace(/\/+$/, '')
	const headers = { 'Content-Type': 'application/json' }
	if (opts.apiKey) headers['X-API-Key'] = opts.apiKey
	const controller = opts.controller

	const parts = String(text || '').trim().split(/\s+/)
	const cmd = (parts.shift() || '').toLowerCase()

	function req(endpoint, payload) {
		const body = controller ? Object.assign({ controller }, payload) : payload
		return { method: 'POST', url: base + endpoint, headers, body: JSON.stringify(body) }
	}

	try {
		switch (cmd) {
			case '':
			case 'help':
				return { reply: HELP }
			case 'scene': {
				const scene = int(parts[0], 'scene', 0, 15)
				const line = int(parts[1], 'line', 1, 4, 1)
				return { request: req('/api/v1/dali/scene', { line, scene }), reply: `Recalling scene ${scene} on line ${line}…` }
			}
			case 'on':
			case 'off': {
				const address = int(parts[0], 'address', 0, 63)
				const line = int(parts[1], 'line', 1, 4, 1)
				return { request: req('/api/v1/dali/command', { line, address, command: cmd }), reply: `Turning address ${address} ${cmd}…` }
			}
			case 'level': {
				const address = int(parts[0], 'address', 0, 63)
				const level = int(parts[1], 'level', 0, 254)
				const line = int(parts[2], 'line', 1, 4, 1)
				return { request: req('/api/v1/dali/level', { line, address, level }), reply: `Setting address ${address} to ${level}…` }
			}
			case 'group': {
				const group = int(parts[0], 'group', 0, 15)
				const level = int(parts[1], 'level', 0, 254)
				const line = int(parts[2], 'line', 1, 4, 1)
				return { request: req('/api/v1/dali/group/level', { line, group, level }), reply: `Setting group ${group} to ${level}…` }
			}
			case 'color': {
				const hex = parts[0]
				if (!/^#?[0-9a-fA-F]{6}$/.test(hex || '')) return { reply: 'Usage: /edidio color #RRGGBB [line]' }
				const line = int(parts[1], 'line', 1, 4, 2)
				return { request: req('/api/v1/dmx/color', { line, hex }), reply: `Setting line ${line} to ${hex}…` }
			}
			case 'seq': {
				const index = int(parts[0], 'index', 0, 65535, 0)
				const zone = int(parts[1], 'zone', 0, 255, 1)
				return { request: req('/api/v1/spektra', { zone, type: 'sequence', index, action: 'start' }), reply: `Starting sequence ${index} on zone ${zone}…` }
			}
			default:
				return { reply: `Unknown command "${cmd}".\n${HELP}` }
		}
	} catch (err) {
		return { reply: `:warning: ${err.message}` }
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
	'*eDIDIO lighting* — `/edidio <command>`:',
	'`scene <0-15> [line]` · `on <addr> [line]` · `off <addr> [line]`',
	'`level <addr> <0-254> [line]` · `group <0-15> <0-254> [line]`',
	'`color <#RRGGBB> [line]` · `seq <index> [zone]`',
].join('\n')

module.exports = { handleCommand, HELP }
