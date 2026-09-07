// Microsoft Teams Outgoing Webhook signature verification.
//
// Teams signs the raw request body with HMAC-SHA256 using the base64-decoded
// shared secret it gave you when you created the outgoing webhook, and sends it
// as `Authorization: HMAC <base64signature>`. We recompute and compare.
//
// Pure (crypto only) so it is unit testable.

const crypto = require('node:crypto')

// Compute the expected `HMAC <sig>` auth header value for a raw body + secret.
function computeAuth(rawBody, base64Secret) {
	const key = Buffer.from(base64Secret, 'base64')
	const sig = crypto.createHmac('sha256', key).update(rawBody).digest('base64')
	return 'HMAC ' + sig
}

// Constant-time compare of the provided Authorization header against expected.
function verify(rawBody, base64Secret, authHeader) {
	if (!base64Secret) return true // not configured (dev only)
	if (!authHeader) return false
	const expected = computeAuth(rawBody, base64Secret)
	const a = Buffer.from(authHeader)
	const b = Buffer.from(expected)
	if (a.length !== b.length) return false
	try {
		return crypto.timingSafeEqual(a, b)
	} catch {
		return false
	}
}

module.exports = { computeAuth, verify }
