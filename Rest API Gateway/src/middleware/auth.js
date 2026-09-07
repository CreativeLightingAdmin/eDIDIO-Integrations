// Optional shared-secret API-key gate.
//
// If config.apiKey is set, every request must present it as `X-API-Key` or
// `Authorization: Bearer <key>`. If it's blank, auth is disabled (only sensible
// on a trusted, isolated network) and a one-time warning is logged at startup.

const { config } = require('../config');
const { ApiError } = require('./errors');

function extractKey(req) {
	const header = req.get('x-api-key');
	if (header) return header.trim();
	const auth = req.get('authorization');
	if (auth && /^bearer\s+/i.test(auth)) return auth.replace(/^bearer\s+/i, '').trim();
	return null;
}

function apiKeyAuth(req, res, next) {
	if (!config.apiKey) return next(); // auth disabled
	const provided = extractKey(req);
	if (provided && provided === config.apiKey) return next();
	next(new ApiError(401, 'Missing or invalid API key.'));
}

module.exports = { apiKeyAuth };
