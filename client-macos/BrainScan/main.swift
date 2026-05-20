import AppKit

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
// .accessory = menubar-only, без dock-иконки и без главного меню в полосе.
app.setActivationPolicy(.accessory)
app.run()
