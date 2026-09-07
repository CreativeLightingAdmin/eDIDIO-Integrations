// Configuration loader. Connection settings from environment (.env); the trigger
// map from triggers.json (falling back to the bundled example).

const path = require('node:path')
const fs = require('node:fs')

try {
	require('dotenv').config({ path: path.join(__dirname, '..', '.env') })
} catch {
	/* dotenv optional */
}

function loadTriggers() {
	const dir = path.join(__dirname)
	const custom = path.join(dir, 'triggers.json')
	const example = path.join(dir, 'triggers.example.json')
	return JSON.parse(fs.readFileSync(fs.existsSync(custom) ? custom : example, 'utf8'))
}

const config = {
	// OBS WebSocket (Tools -> WebSocket Server Settings in OBS).
	obsUrl: process.env.OBS_URL || 'ws://127.0.0.1:4455',
	obsPassword: process.env.OBS_PASSWORD || '',

	// eDIDIO controller.
	edidioHost: process.env.EDIDIO_HOST || '',
	edidioPort: Number(process.env.EDIDIO_PORT || 23),
	edidioUseTLS: /^(1|true|yes|on)$/i.test(process.env.EDIDIO_USE_TLS || ''),

	triggers: loadTriggers(),
}

function assertConfigured() {
	if (!config.edidioHost) {
		throw new Error('Missing EDIDIO_HOST. Set it (and OBS_URL/OBS_PASSWORD) in a .env file (see .env.example).')
	}
}

module.exports = { config, assertConfigured }
