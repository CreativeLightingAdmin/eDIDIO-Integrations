// eDIDIO OBS Studio integration entry point.
//
// Connects to OBS via OBS WebSocket (v5) and to the eDIDIO controller, and drives
// lighting from OBS events:
//   - CurrentProgramSceneChanged -> per-scene action
//   - StreamStateChanged         -> stream start/stop action
//   - RecordStateChanged         -> record start/stop action

const OBSWebSocket = require('obs-websocket-js').default
const { config, assertConfigured } = require('./src/config')
const { ControllerConnection } = require('./src/edidio/connection')
const { handleSceneChange, handleStream, handleRecord } = require('./src/mapper')

async function main() {
	assertConfigured()

	const conn = new ControllerConnection(config.edidioHost, {
		port: config.edidioPort,
		useTLS: config.edidioUseTLS,
	})
	conn.on('connect', () => console.log(`[edidio] connected to ${config.edidioHost}`))
	conn.on('disconnect', () => console.warn('[edidio] disconnected; retrying'))
	conn.connect().catch(() => {})

	async function fire(result) {
		if (!result) return
		if (result.error) {
			console.warn(`[edidio] config error: ${result.error}`)
			return
		}
		const sent = await conn.send(result.frame).catch(() => false)
		console.log(`[edidio] ${sent ? '💡 ' + result.label : '⚠️ not connected (' + result.label + ')'}`)
	}

	const obs = new OBSWebSocket()

	obs.on('CurrentProgramSceneChanged', (data) => {
		console.log(`[obs] scene -> ${data.sceneName}`)
		fire(handleSceneChange(config.triggers, data.sceneName))
	})

	// OBS v5 StreamStateChanged/RecordStateChanged carry outputActive + outputState.
	obs.on('StreamStateChanged', (data) => {
		if (data.outputState === 'OBS_WEBSOCKET_OUTPUT_STARTED' || data.outputState === 'OBS_WEBSOCKET_OUTPUT_STOPPED') {
			fire(handleStream(config.triggers, !!data.outputActive))
		}
	})
	obs.on('RecordStateChanged', (data) => {
		if (data.outputState === 'OBS_WEBSOCKET_OUTPUT_STARTED' || data.outputState === 'OBS_WEBSOCKET_OUTPUT_STOPPED') {
			fire(handleRecord(config.triggers, !!data.outputActive))
		}
	})

	obs.on('ConnectionClosed', () => console.warn('[obs] connection closed'))

	try {
		await obs.connect(config.obsUrl, config.obsPassword || undefined)
		console.log(`[obs] connected to ${config.obsUrl}`)
	} catch (err) {
		console.error(`[obs] connect failed: ${err.message || err}. Is OBS running with WebSocket enabled?`)
		process.exit(1)
	}
}

main().catch((err) => {
	console.error(err.message || err)
	process.exit(1)
})
