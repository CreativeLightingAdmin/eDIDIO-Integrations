// Node behaviour tests using node-red-node-test-helper. Each action node is
// wired to a fake controller (which captures frames); we fire an input and
// decode the produced protobuf frame to assert the exact command.

const helper = require('node-red-node-test-helper');
const should = require('should');

const fakeController = require('./fake-controller');
const daliNode = require('../nodes/edidio-dali');
const dmxNode = require('../nodes/edidio-dmx');
const spektraNode = require('../nodes/edidio-spektra');
const pb = require('../lib/eDS10_ProtocolBuffer_pb.js');

helper.init(require.resolve('node-red'));

function decode(buf) {
	buf[0].should.equal(0xcd);
	const len = (buf[1] << 8) | buf[2];
	len.should.equal(buf.length - 3);
	return pb.EdidioMessage.deserializeBinary(new Uint8Array(buf.slice(3)));
}

// Build a flow: fake controller (c1) -> action node (n1) -> helper (h1).
function flow(nodeType, nodeProps) {
	return [
		{ id: 'c1', type: 'edidio-controller', connected: true },
		Object.assign({ id: 'n1', type: nodeType, controller: 'c1', wires: [['h1']] }, nodeProps),
		{ id: 'h1', type: 'helper' },
	];
}

describe('eDIDIO nodes', function () {
	before(function (done) {
		helper.startServer(done);
	});

	after(function (done) {
		helper.stopServer(done);
	});

	afterEach(function () {
		helper.unload();
	});

	it('edidio-dali: set level builds a DALI arc-level frame', function (done) {
		const nodes = [fakeController, daliNode];
		helper.load(nodes, flow('edidio-dali', { action: 'level', line: 1, address: 5, level: 200 }), function () {
			const n1 = helper.getNode('n1');
			const c1 = helper.getNode('c1');
			const h1 = helper.getNode('h1');
			h1.on('input', function (msg) {
				try {
					msg.payload.sent.should.be.true();
					c1.sent.should.have.length(1);
					const d = decode(c1.sent[0]).getDaliMessage();
					d.getAddress().should.equal(5);
					d.getArg().should.equal(200);
					d.getLineMask().should.equal(0b0001);
					done();
				} catch (err) {
					done(err);
				}
			});
			n1.receive({ payload: {} });
		});
	});

	it('edidio-dali: msg.payload overrides configured defaults', function (done) {
		helper.load([fakeController, daliNode], flow('edidio-dali', { action: 'level', line: 1, address: 0, level: 0 }), function () {
			const n1 = helper.getNode('n1');
			const c1 = helper.getNode('c1');
			const h1 = helper.getNode('h1');
			h1.on('input', function () {
				try {
					const d = decode(c1.sent[0]).getDaliMessage();
					d.getAddress().should.equal(9);
					d.getArg().should.equal(128);
					done();
				} catch (err) {
					done(err);
				}
			});
			n1.receive({ payload: { address: 9, level: 128 } });
		});
	});

	it('edidio-dali: scene recall (broadcast)', function (done) {
		helper.load([fakeController, daliNode], flow('edidio-dali', { action: 'scene', line: 2, scene: 3 }), function () {
			const n1 = helper.getNode('n1');
			const c1 = helper.getNode('c1');
			const h1 = helper.getNode('h1');
			h1.on('input', function () {
				try {
					const d = decode(c1.sent[0]).getDaliMessage();
					// GO TO SCENE 3 (0x10 + 3) broadcast to address 80
					d.getAddress().should.equal(80);
					d.getCommand().should.equal(0x10 + 3);
					d.getLineMask().should.equal(0b0010);
					done();
				} catch (err) {
					done(err);
				}
			});
			n1.receive({ payload: {} });
		});
	});

	it('edidio-dmx: RGB colour frame', function (done) {
		helper.load([fakeController, dmxNode], flow('edidio-dmx', { action: 'color', line: 2, hex: '#FF0000', fixtures: 10 }), function () {
			const n1 = helper.getNode('n1');
			const c1 = helper.getNode('c1');
			const h1 = helper.getNode('h1');
			h1.on('input', function () {
				try {
					const d = decode(c1.sent[0]).getDmxMessage();
					d.getLevelList().should.eql([255, 0, 0]);
					d.getRepeat().should.equal(10);
					d.getUniverseMask().should.equal(0b0010);
					done();
				} catch (err) {
					done(err);
				}
			});
			n1.receive({ payload: {} });
		});
	});

	it('edidio-spektra: start sequence frame', function (done) {
		helper.load([fakeController, spektraNode], flow('edidio-spektra', { target: 'sequence', zone: 1, index: 2, action: 'start' }), function () {
			const n1 = helper.getNode('n1');
			const c1 = helper.getNode('c1');
			const h1 = helper.getNode('h1');
			h1.on('input', function () {
				try {
					const s = decode(c1.sent[0]).getSpektraControl();
					s.getType().should.equal(1); // SEQUENCE
					s.getZone().should.equal(1);
					s.getIndex().should.equal(2);
					s.getAction().should.equal(0); // START
					done();
				} catch (err) {
					done(err);
				}
			});
			n1.receive({ payload: {} });
		});
	});

	it('errors when the controller is not connected', function (done) {
		const f = [
			{ id: 'c1', type: 'edidio-controller', connected: false },
			{ id: 'n1', type: 'edidio-dali', controller: 'c1', action: 'level', line: 1, address: 5, level: 200, wires: [['h1']] },
			{ id: 'h1', type: 'helper' },
		];
		helper.load([fakeController, daliNode], f, function () {
			const n1 = helper.getNode('n1');
			n1.on('call:error', function () {
				done();
			});
			n1.receive({ payload: {} });
		});
	});
});
