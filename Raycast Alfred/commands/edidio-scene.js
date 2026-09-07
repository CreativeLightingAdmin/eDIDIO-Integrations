#!/usr/bin/env node
// Raycast Script Command: recall an eDIDIO scene.
//
// @raycast.schemaVersion 1
// @raycast.title eDIDIO Scene
// @raycast.mode compact
// @raycast.packageName eDIDIO
// @raycast.icon 💡
// @raycast.argument1 { "type": "text", "placeholder": "scene number" }
//
// Configure the gateway via env in Raycast (or your shell): EDIDIO_GATEWAY,
// EDIDIO_API_KEY, EDIDIO_CONTROLLER.

const { run } = require('../lib/edidio')

run(['scene', process.argv[2]], process)
	.then(() => console.log(`Recalled scene ${process.argv[2]}`))
	.catch((err) => {
		console.error(String(err.message || err))
		process.exit(1)
	})
