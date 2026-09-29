// REST gateway tests: API-key rules, the fail-closed startup guard, and live
// state/SSE against a fake controller socket. No hardware required.

process.env.EDIDIO_API_KEY = 'control-key';
process.env.EDIDIO_READ_API_KEY = 'read-key';
process.env.EDIDIO_EVENTS = 'true';
process.env.HOST = '127.0.0.1';

const test = require('node:test');
const assert = require('node:assert/strict');
const net = require('node:net');
const { createApp } = require('../src/server');
const { startupSecurityError } = require('../src/middleware/auth');
const mgr = require('../src/connectionManager');
const discovery = require('../src/edidio/discovery');

// Skip the UDP discovery probe during tests.
discovery.discoverControllers = async () => [];

// Python-engine fixture: event_stream push, line 1 (0-based), 16-bit frame 0x0AC8
// = short address 5 arc 200.
const DALI_PUSH = Buffer.from('ea040e280540039201070801180128c815', 'hex');
const framed = (body) => Buffer.concat([Buffer.from([0xcd, 0, body.length]), body]);

function listen(server) {
	return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server.address().port)));
}

async function withGateway(fn) {
	const server = createApp().listen(0, '127.0.0.1');
	await new Promise((r) => server.once('listening', r));
	const base = `http://127.0.0.1:${server.address().port}/api/v1`;
	try {
		await fn(base);
	} finally {
		mgr.closeAll();
		server.closeAllConnections?.();
		await new Promise((r) => server.close(r));
	}
}

test('startup guard refuses a public bind without a key', () => {
	const base = { apiKey: '', readApiKey: '', allowUnauthenticated: false };
	assert.match(startupSecurityError({ ...base, host: '0.0.0.0' }), /Refusing/);
	assert.equal(startupSecurityError({ ...base, host: '127.0.0.1' }), null);
	assert.equal(startupSecurityError({ ...base, host: '0.0.0.0', allowUnauthenticated: true }), null);
	assert.equal(startupSecurityError({ ...base, host: '0.0.0.0', apiKey: 'k' }), null);
});

test('control key, read-only key, and bad key', async () => {
	await withGateway(async (base) => {
		const get = (key, q = '') => fetch(`${base}/controllers${q}`, key ? { headers: { 'X-API-Key': key } } : {});
		assert.equal((await get(null)).status, 401);
		assert.equal((await get('wrong')).status, 401);
		assert.equal((await get('read-key')).status, 200);
		assert.equal((await get(null, '?api_key=read-key')).status, 200); // EventSource style
		assert.equal((await get('control-key')).status, 200);

		const post = (key, q = '') => fetch(`${base}/dali/level${q}`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json', ...(key ? { Authorization: `Bearer ${key}` } : {}) },
			body: JSON.stringify({ controller: '127.0.0.1', address: 1, level: 1 }),
		});
		assert.equal((await post('read-key')).status, 403);
		assert.equal((await post(null, '?api_key=control-key')).status, 401); // query key is GET-only
	});
});

test('state + SSE reflect DALI frames pushed by the controller', async () => {
	const received = [];
	let sock;
	const fake = net.createServer((s) => {
		sock = s;
		s.on('data', (d) => received.push(Buffer.from(d)));
	});
	const port = await listen(fake);

	await withGateway(async (base) => {
		const headers = { 'X-API-Key': 'control-key', 'Content-Type': 'application/json' };
		const r = await fetch(`${base}/controllers`, {
			method: 'POST', headers, body: JSON.stringify({ ip: '127.0.0.1', port, useTLS: false }),
		});
		assert.equal(r.status, 200);
		// The gateway subscribed to the event stream on connect.
		await waitFor(() => Buffer.concat(received).includes(Buffer.from([0xea, 0x04])));

		const ctrl = new AbortController();
		const sse = await fetch(`${base}/controllers/127.0.0.1/events?api_key=read-key`, { signal: ctrl.signal });
		assert.match(sse.headers.get('content-type'), /^text\/event-stream/);
		const reader = sse.body.getReader();
		let text = '';
		const readUntil = async (needle) => {
			while (!text.includes(needle)) text += Buffer.from((await reader.read()).value).toString();
		};
		try {
			await readUntil('event: snapshot');
			sock.write(Buffer.concat([Buffer.from([0xff, 0xf6]), framed(DALI_PUSH)])); // keep-alive + push
			await readUntil('event: state');
			assert.match(text, /"address":5/);
			assert.match(text, /"level":200/);
		} finally {
			ctrl.abort();
		}

		const state = await (await fetch(`${base}/controllers/127.0.0.1/state`, { headers })).json();
		assert.equal(state.levels['2:5'], 200);
	});
	sock?.destroy();
	fake.close();
});

async function waitFor(pred) {
	for (let i = 0; i < 200; i++) {
		if (pred()) return;
		await new Promise((r) => setTimeout(r, 10));
	}
	throw new Error('condition not met');
}
