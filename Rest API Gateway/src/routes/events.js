// Live state + events (firmware >= 1.4.0 event stream).
//
//   GET /api/v1/controllers/:ip/state   current DALI levels seen on the bus
//   GET /api/v1/controllers/:ip/events  Server-Sent Events: `event` + `state`
//
// Levels reflect *every* change on the bus — wall panels, schedules, SpektraPlus,
// other gateways — not just commands sent through this gateway. Keys are
// "line:address" with eDIDIO addressing (0-63 short, 64+g group, 80 broadcast).

const express = require('express');
const { asyncHandler, ApiError } = require('../middleware/errors');
const mgr = require('../connectionManager');

const router = express.Router();
const SSE_PING_MS = 25000;

function connectionFor(ip) {
	const conn = mgr.getConnection(ip);
	if (!conn) throw new ApiError(404, `No connection for ${ip}. POST /controllers first.`);
	if (conn.eventMask === null) {
		throw new ApiError(409, 'Live events are disabled (EDIDIO_EVENTS=false).');
	}
	return conn;
}

router.get(
	'/controllers/:ip/state',
	asyncHandler(async (req, res) => {
		const conn = connectionFor(req.params.ip);
		res.json({
			ok: true,
			controller: req.params.ip,
			connected: conn.connected,
			lastEventAt: conn.lastEventAt,
			levels: conn.levels.snapshot(),
		});
	}),
);

router.get('/controllers/:ip/events', (req, res, next) => {
	let conn;
	try {
		conn = connectionFor(req.params.ip);
	} catch (err) {
		return next(err);
	}
	res.set({
		'Content-Type': 'text/event-stream',
		'Cache-Control': 'no-cache',
		Connection: 'keep-alive',
		'X-Accel-Buffering': 'no', // don't let nginx buffer the stream
	});
	res.flushHeaders();

	const send = (type, data) => res.write(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`);
	send('snapshot', { levels: conn.levels.snapshot() });

	const onEvent = (ev) => send('event', ev);
	const onState = (st) => send('state', st);
	conn.on('event', onEvent);
	conn.on('state', onState);
	const ping = setInterval(() => res.write(': ping\n\n'), SSE_PING_MS);

	req.on('close', () => {
		clearInterval(ping);
		conn.off('event', onEvent);
		conn.off('state', onState);
	});
});

module.exports = router;
