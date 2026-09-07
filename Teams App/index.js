// eDIDIO Microsoft Teams app: an Outgoing Webhook endpoint that forwards
// lighting commands to the eDIDIO REST API Gateway.
//
//   Teams "@eDIDIO scene 3" -> POST /teams -> REST gateway -> eDIDIO

const path = require('node:path')
const express = require('express')

try {
	require('dotenv').config({ path: path.join(__dirname, '.env') })
} catch {
	/* dotenv optional */
}

const { handleCommand } = require('./src/mapper')
const { verify } = require('./src/verify')
const { extractCommand } = require('./src/extract')

const PORT = Number(process.env.PORT || 3978)
const SECRET = process.env.TEAMS_SECRET || '' // base64 shared secret from Teams
const BOT_NAME = process.env.TEAMS_BOT_NAME || 'eDIDIO'
const OPTS = {
	gatewayUrl: process.env.EDIDIO_GATEWAY_URL || 'http://localhost:8080',
	apiKey: process.env.EDIDIO_API_KEY || '',
	controller: process.env.EDIDIO_CONTROLLER || '',
}

const app = express()
// Keep the raw body for HMAC verification.
app.use(express.json({ verify: (req, _res, buf) => { req.rawBody = buf } }))

app.post('/teams', async (req, res) => {
	if (!verify(req.rawBody || Buffer.from(''), SECRET, req.get('Authorization'))) {
		return res.status(401).json({ type: 'message', text: 'Unauthorised.' })
	}

	const text = extractCommand(req.body, BOT_NAME)
	const result = handleCommand(text, OPTS)

	// Reply immediately so Teams shows feedback.
	res.json({ type: 'message', text: result.reply })

	if (result.request) {
		try {
			await fetch(result.request.url, {
				method: result.request.method,
				headers: result.request.headers,
				body: result.request.body,
			})
		} catch (err) {
			console.warn(`[edidio] gateway call failed: ${err.message}`)
		}
	}
})

app.get('/health', (_req, res) => res.json({ ok: true }))

app.listen(PORT, () => {
	console.log(`eDIDIO Teams app listening on :${PORT} -> gateway ${OPTS.gatewayUrl}`)
	if (!SECRET) console.warn('[teams] TEAMS_SECRET not set — signature check disabled (dev only)')
})
