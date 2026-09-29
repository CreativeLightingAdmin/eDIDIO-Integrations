// Centralised configuration loader for the REST gateway.
//
// Values come from environment variables (via a gitignored .env file). No
// secrets are ever committed.

const path = require('node:path');

try {
	require('dotenv').config({ path: path.join(__dirname, '..', '.env') });
} catch {
	/* dotenv is optional; fall back to real environment variables */
}

function bool(value, fallback = false) {
	if (value === undefined || value === null || value === '') return fallback;
	return /^(1|true|yes|on)$/i.test(String(value));
}

const config = {
	// HTTP server.
	port: Number(process.env.PORT || 8080),
	host: process.env.HOST || '0.0.0.0',

	// Shared-secret API keys. EDIDIO_API_KEY grants full control; the optional
	// EDIDIO_READ_API_KEY only allows GET (status, state, live events).
	apiKey: process.env.EDIDIO_API_KEY || '',
	readApiKey: process.env.EDIDIO_READ_API_KEY || '',
	// Without a key the gateway refuses to listen on a non-loopback address
	// unless this is explicitly set (trusted, isolated networks only).
	allowUnauthenticated: bool(process.env.EDIDIO_ALLOW_UNAUTHENTICATED, false),

	// Live events: subscribe each controller connection to its event stream
	// (firmware >= 1.4.0) so /state and /events report real device state.
	events: bool(process.env.EDIDIO_EVENTS, true),
	eventCategories: (process.env.EDIDIO_EVENT_CATEGORIES || 'dali,inputs,sensors,triggers')
		.split(',').map((s) => s.trim()).filter(Boolean),

	// Controller defaults. Plain TCP is port 23; TLS is port 443.
	controllerPort: Number(process.env.EDIDIO_PORT || 23),
	controllerTlsPort: Number(process.env.EDIDIO_TLS_PORT || 443),
	defaultControllerIp: process.env.EDIDIO_IP || null,
	defaultUseTLS: bool(process.env.EDIDIO_USE_TLS, false),

	// Keep-alive heartbeat interval (ms) to keep controller sockets alive.
	heartbeatIntervalMs: Number(process.env.HEARTBEAT_MS || 7000),
};

module.exports = { config };
