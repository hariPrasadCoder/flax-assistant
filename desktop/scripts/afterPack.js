/**
 * electron-builder afterPack hook
 * Runs after app is packed but before DMG is created.
 * Ad-hoc signs the .app so macOS shows "unidentified developer"
 * instead of "damaged" — allowing users to open via right-click or Privacy settings.
 */

const { execSync } = require('child_process')
const path = require('path')

module.exports = async function afterPack(context) {
  if (context.electronPlatformName !== 'darwin') return

  const appName = context.packager.appInfo.productFilename
  const appPath = path.join(context.appOutDir, `${appName}.app`)

  console.log(`\nAd-hoc signing: ${appPath}`)
  try {
    execSync(`codesign --force --deep --sign - "${appPath}"`, { stdio: 'inherit' })
    console.log('Ad-hoc signing complete.\n')
  } catch (e) {
    console.warn('Ad-hoc signing failed (non-fatal):', e.message)
  }
}
