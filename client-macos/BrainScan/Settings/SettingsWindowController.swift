import AppKit
import SwiftUI

/// Нативное окно настроек: стандартный titled-window, контент — SwiftUI
/// `SettingsView` через NSHostingController (надёжный layout + system look).
final class SettingsWindowController: NSWindowController {
    var status: WidgetStatus = .noServer(localAnnotations: 0) {
        didSet { hosting?.rootView = makeView() }
    }
    /// Sign Out — клик по «Change…» в секции Account. Чистит токены и возвращает
    /// на экран входа (логика — в AppDelegate).
    var onSignOut: (() -> Void)?

    private var hosting: NSHostingController<SettingsView>?

    convenience init() {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 460, height: 620),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Settings"
        window.isReleasedWhenClosed = false
        self.init(window: window)

        let hosting = NSHostingController(rootView: makeView())
        window.contentViewController = hosting
        self.hosting = hosting
    }

    /// LSUIElement-приложение не активно по умолчанию — без `activate`
    /// окно не выйдет на передний план.
    func present() {
        guard let window else { return }
        if !window.isVisible {
            window.center()
        }
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
    }

    private func makeView() -> SettingsView {
        SettingsView(
            statusText: status.primaryText,
            statusColor: Color(status.dotColor),
            statusMeta: metaLine,
            onSignOut: { [weak self] in self?.onSignOut?() }
        )
    }

    private var metaLine: String {
        switch status {
        case let .connected(localizer, tumor):
            return "Localizer \(localizer) · Tumor Detector \(tumor)"
        default:
            return status.secondaryLines.first ?? ""
        }
    }
}
