// RTI driver logic tests using a fake host (no device). Run with: node --test

const test = require('node:test');
const assert = require('node:assert');
const f = require('../src/edidio_frames.js');
const { EdidioDriver } = require('../src/driver.js');

const MID1 = 1;

function hex(bytes) {
	return Buffer.from(bytes).toString('hex');
}

function makeHost() {
	return {
		sent: [],
		vars: {},
		logs: [],
		send(bytes) { this.sent.push(Buffer.from(bytes)); },
		setVariable(name, value) { this.vars[name] = value; },
		log(msg) { this.logs.push(msg); },
	};
}

function make() {
	const host = makeHost();
	const d = new EdidioDriver(host);
	d.onConnect();
	return { d, host };
}

test('onConnect sets connection variable', () => {
	const { host } = make();
	assert.strictEqual(host.vars.ConnectionStatus, 'Connected');
});

test('setLevel frame', () => {
	const { d, host } = make();
	d.setLevel(1, 5, 200);
	assert.strictEqual(hex(host.sent.at(-1)), hex(f.daliArcLevel(MID1, f.lineMask(1), 5, 200)));
});

test('setGroupLevel frame', () => {
	const { d, host } = make();
	d.setGroupLevel(1, 3, 128);
	assert.strictEqual(hex(host.sent.at(-1)), hex(f.daliGroupArcLevel(MID1, f.lineMask(1), 3, 128)));
});

test('on/off frames', () => {
	const { d, host } = make();
	d.on(2, 10);
	assert.strictEqual(hex(host.sent.at(-1)), hex(f.daliCommand(MID1, f.lineMask(2), 10, 'on')));
	d.off(2, 10);
	assert.strictEqual(hex(host.sent.at(-1)), hex(f.daliCommand(2, f.lineMask(2), 10, 'off')));
});

test('recallScene broadcast and on-group', () => {
	const { d, host } = make();
	d.recallScene(1, 3);
	assert.strictEqual(hex(host.sent.at(-1)), hex(f.daliBroadcastScene(MID1, f.lineMask(1), 3)));
	d.recallScene(1, 3, 4);
	assert.strictEqual(hex(host.sent.at(-1)), hex(f.daliSceneOnGroup(2, f.lineMask(1), 4, 3)));
});

test('dmxColor frame', () => {
	const { d, host } = make();
	d.dmxColor(2, '#FF0000', 10);
	assert.strictEqual(hex(host.sent.at(-1)), hex(f.dmxLevel(MID1, 0xff, f.lineMask(2), 1, 10, [255, 0, 0])));
});

test('spektra frame', () => {
	const { d, host } = make();
	d.spektra(1, 'sequence', 2, 'start');
	assert.strictEqual(hex(host.sent.at(-1)), hex(f.spektraControl(MID1, f.SPEKTRA_SEQUENCE, 1, 2, f.SPEKTRA_START)));
});

test('spektraStop frame', () => {
	const { d, host } = make();
	d.spektraStop(1);
	assert.strictEqual(hex(host.sent.at(-1)), hex(f.spektraStop(MID1, 1)));
});

test('keepAlive sends heartbeat only when connected', () => {
	const { d, host } = make();
	const n = host.sent.length;
	d.keepAlive();
	assert.strictEqual(hex(host.sent.at(-1)), hex(f.KEEP_ALIVE));
	d.onDisconnect();
	const m = host.sent.length;
	d.keepAlive();
	assert.strictEqual(host.sent.length, m); // nothing sent while disconnected
});

test('onDisconnect updates variable', () => {
	const { d, host } = make();
	d.onDisconnect();
	assert.strictEqual(host.vars.ConnectionStatus, 'Disconnected');
});

test('message ids increment', () => {
	const { d, host } = make();
	d.setLevel(1, 0, 10);
	d.setLevel(1, 0, 10);
	assert.notStrictEqual(hex(host.sent.at(-1)), hex(host.sent.at(-2)));
});
