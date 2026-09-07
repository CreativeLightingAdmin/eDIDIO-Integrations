// Shared helper for the Raycast/Alfred eDIDIO commands: turn simple CLI args into
// a request to the eDIDIO REST API Gateway, and (optionally) perform it.
//
// Pure request-building (buildRequest) is unit tested; `run` performs the fetch.
// Configure via env: EDIDIO_GATEWAY (default http://localhost:8080),
// EDIDIO_API_KEY, EDIDIO_CONTROLLER.

'use strict'

function num(v, d) {
	const n = Number(v)
	return Number.isNaN(n) ? d : n
}

// argv: e.g. ["scene","3"] or ["level","5","200"] or ["color","#FF0000"].
// env: { gateway, apiKey, controller }. Returns {method,url,headers,body} or throws.
function buildRequest(argv, env) {
	const base = String(env.gateway || 'http://localhost:8080').replace(/\/+$/, '')
	const headers = { 'Content-Type': 'application/json' }
	if (env.apiKey) headers['X-API-Key'] = env.apiKey
	const common = env.controller ? { controller: env.controller } : {}
	const line = num(env.line, 1)

	const cmd = (argv[0] || '').toLowerCase()
	const a = argv.slice(1)

	function req(endpoint, payload) {
		return { method: 'POST', url: base + endpoint, headers, body: JSON.stringify(Object.assign({}, common, payload)) }
	}

	switch (cmd) {
		case 'scene':
			return req('/api/v1/dali/scene', { line, scene: num(a[0], 0) })
		case 'on':
		case 'off':
			return req('/api/v1/dali/command', { line, address: num(a[0], 0), command: cmd })
		case 'level':
			return req('/api/v1/dali/level', { line, address: num(a[0], 0), level: num(a[1], 254) })
		case 'group':
			return req('/api/v1/dali/group/level', { line, group: num(a[0], 0), level: num(a[1], 254) })
		case 'color':
		case 'colour': {
			const hex = a[0] || ''
			if (!/^#?[0-9a-fA-F]{6}$/.test(hex)) throw new Error('usage: color <#RRGGBB>')
			return req('/api/v1/dmx/color', { line: num(env.dmxLine, 2), hex })
		}
		case 'seq':
			return req('/api/v1/spektra', { zone: num(a[1], 1), type: 'sequence', index: num(a[0], 0), action: 'start' })
		default:
			throw new Error(`unknown command "${cmd}". Try: scene|on|off|level|group|color|seq`)
	}
}

function envFrom(process) {
	return {
		gateway: process.env.EDIDIO_GATEWAY,
		apiKey: process.env.EDIDIO_API_KEY,
		controller: process.env.EDIDIO_CONTROLLER,
		line: process.env.EDIDIO_LINE,
		dmxLine: process.env.EDIDIO_DMX_LINE,
	}
}

async function run(argv, process) {
	const req = buildRequest(argv, envFrom(process))
	const res = await fetch(req.url, { method: req.method, headers: req.headers, body: req.body })
	if (!res.ok) throw new Error(`gateway ${res.status}`)
	return req
}

module.exports = { buildRequest, envFrom, run }
