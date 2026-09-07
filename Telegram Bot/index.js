// eDIDIO Telegram bot entry point.
//
// Connects to Telegram (long polling) and the eDIDIO controller, and routes
// slash-commands through the pure mapper into eDIDIO frames. An optional
// allowlist of chat IDs restricts who can control the lighting.

const path = require('node:path')
try {
	require('dotenv').config({ path: path.join(__dirname, '.env') })
} catch {
	/* dotenv optional */
}

const TelegramBot = require('node-telegram-bot-api')
const { ControllerConnection } = require('./src/edidio/connection')
const { handleCommand } = require('./src/mapper')

const TOKEN = process.env.TELEGRAM_TOKEN || ''
const EDIDIO_HOST = process.env.EDIDIO_HOST || ''
const EDIDIO_PORT = Number(process.env.EDIDIO_PORT || 23)
const EDIDIO_USE_TLS = /^(1|true|yes|on)$/i.test(process.env.EDIDIO_USE_TLS || '')
const ALLOWED = (process.env.ALLOWED_CHAT_IDS || '')
	.split(',')
	.map((s) => s.trim())
	.filter(Boolean)

function assertConfigured() {
	const missing = []
	if (!TOKEN) missing.push('TELEGRAM_TOKEN')
	if (!EDIDIO_HOST) missing.push('EDIDIO_HOST')
	if (missing.length) throw new Error(`Missing config: ${missing.join(', ')} (see .env.example)`)
}

function allowed(chatId) {
	return ALLOWED.length === 0 || ALLOWED.includes(String(chatId))
}

function main() {
	assertConfigured()

	const conn = new ControllerConnection(EDIDIO_HOST, { port: EDIDIO_PORT, useTLS: EDIDIO_USE_TLS })
	conn.on('connect', () => console.log(`[edidio] connected to ${EDIDIO_HOST}`))
	conn.on('disconnect', () => console.warn('[edidio] disconnected; retrying'))
	conn.connect().catch(() => {})

	const bot = new TelegramBot(TOKEN, { polling: true })
	console.log('[telegram] bot started (long polling)')
	if (ALLOWED.length === 0) console.warn('[telegram] ALLOWED_CHAT_IDS empty — anyone can control the lights')

	bot.on('message', async (msg) => {
		const text = msg.text || ''
		if (!text.startsWith('/')) return
		if (!allowed(msg.chat.id)) {
			bot.sendMessage(msg.chat.id, `⛔ Not authorised (chat id ${msg.chat.id}).`)
			return
		}
		const result = handleCommand(text)
		if (!result) return // unknown command
		if (result.frame) {
			const sent = await conn.send(result.frame).catch(() => false)
			bot.sendMessage(msg.chat.id, sent ? result.reply : '⚠️ Controller not connected')
		} else {
			bot.sendMessage(msg.chat.id, result.reply)
		}
	})

	bot.on('polling_error', (err) => console.warn(`[telegram] ${err.message}`))
}

try {
	main()
} catch (err) {
	console.error(err.message || err)
	process.exit(1)
}
