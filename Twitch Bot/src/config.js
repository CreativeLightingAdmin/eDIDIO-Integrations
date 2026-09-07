// Configuration loader. Secrets come from environment (.env); the command map
// comes from commands.json (falling back to the bundled example).

const path = require('node:path')
const fs = require('node:fs')

try {
	require('dotenv').config({ path: path.join(__dirname, '..', '.env') })
} catch {
	/* dotenv optional */
}

function loadCommands() {
	const dir = path.join(__dirname)
	const custom = path.join(dir, 'commands.json')
	const example = path.join(dir, 'commands.example.json')
	const file = fs.existsSync(custom) ? custom : example
	return JSON.parse(fs.readFileSync(file, 'utf8'))
}

const config = {
	// Twitch
	username: process.env.TWITCH_USERNAME || '',
	oauth: process.env.TWITCH_OAUTH || '', // 'oauth:xxxx'
	channel: process.env.TWITCH_CHANNEL || '',

	// eDIDIO controller
	edidioHost: process.env.EDIDIO_HOST || '',
	edidioPort: Number(process.env.EDIDIO_PORT || 23),
	edidioUseTLS: /^(1|true|yes|on)$/i.test(process.env.EDIDIO_USE_TLS || ''),

	// Announce command results back into chat.
	announce: !/^(0|false|no|off)$/i.test(process.env.ANNOUNCE || 'true'),

	commands: loadCommands(),
}

function assertConfigured() {
	const missing = []
	for (const k of ['username', 'oauth', 'channel', 'edidioHost']) {
		if (!config[k]) missing.push(k)
	}
	if (missing.length) {
		throw new Error(
			`Missing config: ${missing.join(', ')}. Set TWITCH_USERNAME, TWITCH_OAUTH, ` +
				'TWITCH_CHANNEL and EDIDIO_HOST in a .env file (see .env.example).'
		)
	}
}

module.exports = { config, assertConfigured }
