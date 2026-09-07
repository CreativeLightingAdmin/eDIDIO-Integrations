// Pure mapping: Stream Deck action settings -> an HTTP request to the eDIDIO
// REST API Gateway. Kept side-effect-free (no fetch, no Stream Deck) so it can be
// unit tested in Node and reused by the plugin in the browser context.

(function (root) {
	'use strict'

	function num(v, d) {
		var n = Number(v)
		return isNaN(n) ? d : n
	}

	// settings: { gatewayUrl, apiKey?, controller?, command, line, address, group,
	//             scene, level, hex, zone, type, index, action }
	// Returns { method, url, headers, body } (body is a JSON string) or throws.
	function buildRequest(settings) {
		var base = String(settings.gatewayUrl || 'http://localhost:8080').replace(/\/+$/, '')
		var headers = { 'Content-Type': 'application/json' }
		if (settings.apiKey) headers['X-API-Key'] = settings.apiKey

		var common = {}
		if (settings.controller) common.controller = settings.controller

		var endpoint
		var payload
		switch (settings.command) {
			case 'scene':
				endpoint = '/api/v1/dali/scene'
				payload = { line: num(settings.line, 1), scene: num(settings.scene, 0) }
				if (settings.group !== '' && settings.group != null) payload.group = num(settings.group, 0)
				break
			case 'level':
				endpoint = '/api/v1/dali/level'
				payload = { line: num(settings.line, 1), address: num(settings.address, 0), level: num(settings.level, 254) }
				break
			case 'group_level':
				endpoint = '/api/v1/dali/group/level'
				payload = { line: num(settings.line, 1), group: num(settings.group, 0), level: num(settings.level, 254) }
				break
			case 'on':
			case 'off':
				endpoint = '/api/v1/dali/command'
				payload = { line: num(settings.line, 1), address: num(settings.address, 0), command: settings.command }
				break
			case 'dmx_color':
				endpoint = '/api/v1/dmx/color'
				payload = { line: num(settings.line, 1), hex: settings.hex || '#FF0000' }
				break
			case 'spektra':
				endpoint = '/api/v1/spektra'
				payload = {
					zone: num(settings.zone, 0),
					type: settings.type || 'sequence',
					index: num(settings.index, 0),
					action: settings.action || 'start',
				}
				break
			default:
				throw new Error('unknown command: ' + settings.command)
		}

		var body = {}
		for (var k in common) body[k] = common[k]
		for (var j in payload) body[j] = payload[j]

		return { method: 'POST', url: base + endpoint, headers: headers, body: JSON.stringify(body) }
	}

	if (typeof module !== 'undefined' && module.exports) {
		module.exports = { buildRequest: buildRequest }
	} else {
		root.EdidioRequest = { buildRequest: buildRequest }
	}
})(typeof globalThis !== 'undefined' ? globalThis : this)
