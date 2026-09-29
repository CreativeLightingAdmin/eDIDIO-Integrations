// Pure mapping between the plugin config, HomeKit values and eDIDIO frames.
// No Homebridge dependency, so it is unit tested directly.

const frames = require('./edidio_frames.js')

const DALI_ARC_LEVEL_MAX = 254
const DALI_GROUP_ADDRESS_BASE = 64

function pctToArc(pct) {
	const p = Math.max(0, Math.min(100, Number(pct) || 0))
	return Math.round((p * DALI_ARC_LEVEL_MAX) / 100)
}

function arcToPct(level) {
	const l = Math.max(0, Math.min(DALI_ARC_LEVEL_MAX, Number(level) || 0))
	return Math.round((l * 100) / DALI_ARC_LEVEL_MAX)
}

function int(v, name, lo, hi) {
	const n = Number(v)
	if (!Number.isInteger(n) || n < lo || n > hi) throw new Error(`${name} must be an integer ${lo}-${hi}`)
	return n
}

// Validate one light entry: { name, line, address } or { name, line, group }.
function parseLight(cfg) {
	if (!cfg || !cfg.name) throw new Error('each light needs a name')
	const hasAddr = cfg.address !== undefined && cfg.address !== null && cfg.address !== ''
	const hasGroup = cfg.group !== undefined && cfg.group !== null && cfg.group !== ''
	if (hasAddr === hasGroup) throw new Error(`light "${cfg.name}": set exactly one of address or group`)
	const light = { kind: 'light', name: cfg.name, line: int(cfg.line ?? 1, 'line', 1, 4) }
	if (hasAddr) light.address = int(cfg.address, 'address', 0, 63)
	else light.group = int(cfg.group, 'group', 0, 15)
	light.edidioAddress = hasAddr ? light.address : DALI_GROUP_ADDRESS_BASE + light.group
	light.id = `light:${light.line}:${light.edidioAddress}`
	return light
}

// Validate one scene entry: { name, line, scene, group? }.
function parseScene(cfg) {
	if (!cfg || !cfg.name) throw new Error('each scene needs a name')
	const scene = {
		kind: 'scene',
		name: cfg.name,
		line: int(cfg.line ?? 1, 'line', 1, 4),
		scene: int(cfg.scene, 'scene', 0, 15),
	}
	if (cfg.group !== undefined && cfg.group !== null && cfg.group !== '') scene.group = int(cfg.group, 'group', 0, 15)
	scene.id = `scene:${scene.line}:${scene.group ?? 'all'}:${scene.scene}`
	return scene
}

function levelFrame(light, level, mid) {
	const lm = frames.lineMask(light.line)
	if (light.address !== undefined) return frames.daliArcLevel(mid, lm, light.address, level)
	return frames.daliGroupArcLevel(mid, lm, light.group, level)
}

function sceneFrame(scene, mid) {
	const lm = frames.lineMask(scene.line)
	if (scene.group === undefined) return frames.daliBroadcastScene(mid, lm, scene.scene)
	return frames.daliSceneOnGroup(mid, lm, scene.group, scene.scene)
}

module.exports = { pctToArc, arcToPct, parseLight, parseScene, levelFrame, sceneFrame, DALI_ARC_LEVEL_MAX }
