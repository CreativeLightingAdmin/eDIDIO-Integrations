// eDIDIO REST API Gateway — HTTP entry point.
//
// Exposes a small, resource-oriented REST API that translates standard HTTP
// requests into eDIDIO TCP/TLS protobuf packets (DALI, DMX, SpektraPlus).

const express = require('express');
const { config } = require('./config');
const { apiKeyAuth } = require('./middleware/auth');
const { errorHandler, ApiError } = require('./middleware/errors');
const mgr = require('./connectionManager');

const app = express();
app.disable('x-powered-by');
app.use(express.json({ limit: '256kb' }));

// Health check (unauthenticated) — handy for load balancers and uptime probes.
app.get('/health', (req, res) => {
	res.json({ ok: true, service: 'edidio-rest-gateway', controllers: mgr.listConnections() });
});

// Everything under /api requires the API key (when one is configured).
const api = express.Router();
api.use(apiKeyAuth);
api.use(require('./routes/controllers'));
api.use(require('./routes/dali'));
api.use(require('./routes/dmx'));
api.use(require('./routes/spektra'));
app.use('/api/v1', api);

// 404 for anything unmatched.
app.use((req, res, next) => next(new ApiError(404, `Not found: ${req.method} ${req.path}`)));

app.use(errorHandler);

const server = app.listen(config.port, config.host, () => {
	console.log(`eDIDIO REST gateway listening on http://${config.host}:${config.port}`);
	if (!config.apiKey) {
		console.warn('[gateway] EDIDIO_API_KEY is not set — the API is UNAUTHENTICATED.');
	}
	if (config.defaultControllerIp) {
		console.log(`[gateway] Default controller: ${config.defaultControllerIp}`);
	}
});

// Graceful shutdown: stop reconnect loops and close sockets.
function shutdown(signal) {
	console.log(`\n[gateway] ${signal} received, shutting down...`);
	mgr.closeAll();
	server.close(() => process.exit(0));
	// Force-exit if sockets linger.
	setTimeout(() => process.exit(0), 3000).unref();
}
process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));

module.exports = { app, server };
