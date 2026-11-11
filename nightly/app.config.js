// Wraps upstream's Expo config (renamed to app.config.upstream.js by
// nightly/apply.sh) and changes only what a side-by-side nightly needs.
const upstream = require('./app.config.upstream.js')

module.exports = function (config) {
  const result = upstream(config)
  const expo = result.expo
  expo.name = 'Blacksky Nightly'
  expo.version = process.env.NIGHTLY_VERSION_NAME || expo.version
  expo.updates = {...expo.updates, enabled: false}
  expo.android = {
    ...expo.android,
    package: 'community.blacksky.app.nightly',
    versionCode: Number(process.env.NIGHTLY_VERSION_CODE) || undefined,
    icon: './nightly/android_icon_nightly.png',
    adaptiveIcon: {
      ...expo.android.adaptiveIcon,
      backgroundColor: undefined,
      backgroundImage: './nightly/icon-android-background-nightly.png',
    },
  }
  return result
}
