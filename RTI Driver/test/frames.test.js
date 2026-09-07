// Byte-equality tests for the pure-JS encoder, run with Node's built-in test
// runner:  node --test
//
// Reference hexes captured from edidio_control_py 0.3.0 (message_id=7) — the
// same oracle used by the Python/Extron/AMX encoders.

const test = require('node:test');
const assert = require('node:assert');
const f = require('../src/edidio_frames.js');

const MID = 7;

function hex(bytes) {
	return Buffer.from(bytes).toString('hex');
}

const REFERENCE = {
	arc: 'cd000e080792010908011005300048c801',
	group: 'cd000e0807920109080110433000488001',
	cmd: 'cd000d08079201080802100a28054800',
	cmd_off: 'cd000b0807920106080128004800',
	bscene: 'cd000b0807920106080110502813',
	gscene: 'cd000b0807920106080110442813',
	dmx: 'cd00140807a2010f08ff0110021801200a2a04ff010000',
	dmx_fade: 'cd00120807a2010d1001180120012a030a141e3032',
	spektra: 'cd000b0807da0106080110011802',
	spektra_stop: 'cd000e0807aa01090a07080d100118ff01',
};

test('dali arc level', () => {
	assert.strictEqual(hex(f.daliArcLevel(MID, 1, 5, 200)), REFERENCE.arc);
});

test('dali group arc level', () => {
	assert.strictEqual(hex(f.daliGroupArcLevel(MID, 1, 3, 128)), REFERENCE.group);
});

test('dali command (max)', () => {
	assert.strictEqual(hex(f.daliCommand(MID, 2, 10, f.DALI_MAX_LEVEL)), REFERENCE.cmd);
});

test('dali command off (named)', () => {
	assert.strictEqual(hex(f.daliCommand(MID, 1, 0, 'off')), REFERENCE.cmd_off);
});

test('dali broadcast scene', () => {
	assert.strictEqual(hex(f.daliBroadcastScene(MID, 1, 3)), REFERENCE.bscene);
});

test('dali scene on group', () => {
	assert.strictEqual(hex(f.daliSceneOnGroup(MID, 1, 4, 3)), REFERENCE.gscene);
});

test('dmx level', () => {
	assert.strictEqual(hex(f.dmxLevel(MID, 255, 2, 1, 10, [255, 0, 0])), REFERENCE.dmx);
});

test('dmx level with fade', () => {
	assert.strictEqual(hex(f.dmxLevel(MID, 0, 1, 1, 1, [10, 20, 30], 50)), REFERENCE.dmx_fade);
});

test('spektra control (start sequence)', () => {
	assert.strictEqual(hex(f.spektraControl(MID, f.SPEKTRA_SEQUENCE, 1, 2, f.SPEKTRA_START)), REFERENCE.spektra);
});

test('spektra stop', () => {
	assert.strictEqual(hex(f.spektraStop(MID, 1, 0xff)), REFERENCE.spektra_stop);
});

test('arc level clamps to 254', () => {
	assert.strictEqual(hex(f.daliArcLevel(MID, 1, 5, 999)), hex(f.daliArcLevel(MID, 1, 5, 254)));
});

test('line mask', () => {
	assert.strictEqual(f.lineMask(1), 1);
	assert.strictEqual(f.lineMask(4), 8);
});
