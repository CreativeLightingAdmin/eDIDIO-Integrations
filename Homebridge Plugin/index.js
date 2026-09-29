// homebridge-edidio: Control Freak eDIDIO lighting in Apple Home via Homebridge.

const { EdidioPlatform, PLUGIN_NAME, PLATFORM_NAME } = require('./lib/platform.js')

module.exports = (api) => {
	api.registerPlatform(PLUGIN_NAME, PLATFORM_NAME, EdidioPlatform)
}
