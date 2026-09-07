// eDIDIO Slack app: a slash-command endpoint that forwards lighting commands to
// the eDIDIO REST API Gateway. Verifies Slack's request signature.
//
//   Slack "/edidio scene 3"  ->  POST /slack/command  ->  REST gateway  ->  eDIDIO

const crypto = require('node:crypto')
const path = require('node:path')
const express = require('express')

try {
	require('dotenv').config({ path: path.join(__dirname, '.env') })
} catch {
	/* dotenv optional */
}

const { handleCommand } = require('./src/mapper')

const PORT = Number(process.env.PORT || 3000)
const SIGNING_SECRET = process.env.SLACK_SIGNING_SECRET || ''
const OPTS = {
	gatewayUrl: process.env.EDIDIO_GATEWAY_URL || 'http://localhost:8080',
	apiKey: process.env.EDIDIO_API_KEY || '',
	controller: process.env.EDIDIO_CONTROLLER || '',
}

const app = express()
// Slack sends application/x-www-form-urlencoded; keep the raw body for signing.
app.use(express.urlencoded({ extended: true, verify: (req, _res, buf) => { req.rawBody = buf } }))

// Verify Slack's signature (https://api.slack.com/authentication/verifying-requests-from-slack).
function verifySlack(req) {
	if (!SIGNING_SECRET) return true // not configured (dev only)
	const ts = req.get('X-Slack-Request-Timestamp')
	const sig = req.get('X-Slack-Signature')
	if (!ts || !sig) return false
	// Reject old requests (replay protection).
	if (Math.abs(Date.now() / 1000 - Number(ts)) > 300) return false
	const basestring = `v0:${ts}:${req.rawBody ? req.rawBody.toString() : ''}`
	const mySig = 'v0=' + crypto.createHmac('sha256', SIGNING_SECRET).update(basestring).digest('hex')
	try {
		return crypto.timingSafeEqual(Buffer.from(mySig), Buffer.from(sig))
	} catch {
		return false
	}
}

app.post('/slack/command', async (req, res) => {
	if (!verifySlack(req)) return res.status(401).send('bad signature')

	const result = handleCommand(req.body.text || '', OPTS)

	// Reply immediately (ephemeral) so Slack doesn't time out.
	res.json({ response_type: 'ephemeral', text: result.reply })

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
	console.log(`eDIDIO Slack app listening on :${PORT} -> gateway ${OPTS.gatewayUrl}`)
	if (!SIGNING_SECRET) console.warn('[slack] SLACK_SIGNING_SECRET not set — signature check disabled (dev only)')
})
