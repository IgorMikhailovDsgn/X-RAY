import AppKit
import SwiftUI

/// Окно входа: стандартное titled NSWindow с SwiftUI-контентом через NSHostingController.
/// Показывается на старте, если в Keychain нет токенов, и после Sign Out.
final class SignInWindowController: NSWindowController {
    var onSignedIn: (() -> Void)?

    private let viewModel = SignInViewModel()

    convenience init() {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 380, height: 280),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        window.title = "Sign In"
        window.isReleasedWhenClosed = false
        self.init(window: window)

        viewModel.onSignedIn = { [weak self] in self?.onSignedIn?() }
        window.contentViewController = NSHostingController(rootView: SignInView(viewModel: viewModel))
    }

    func present() {
        guard let window else { return }
        if !window.isVisible { window.center() }
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
    }

    func hide() { window?.orderOut(nil) }
}
