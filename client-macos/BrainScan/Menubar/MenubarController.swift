import AppKit

/// NSStatusItem c «XR»-лейблом. Клик показывает стандартное NSMenu —
/// никаких кастомных цветов, по гайдлайнам macOS (макет Figma — лишь пример
/// структуры пунктов).
final class MenubarController: NSObject {
    private let statusItem: NSStatusItem
    private let statusMenuItem = NSMenuItem()

    var onToggleWidget: (() -> Void)?
    var onAnnotate: (() -> Void)?
    var onDetect: (() -> Void)?
    var onSettings: (() -> Void)?

    var status: WidgetStatus = .noServer(localAnnotations: 0) {
        didSet { statusMenuItem.title = status.primaryText }
    }

    override init() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        super.init()
        configureButton()
        statusItem.menu = buildMenu()
    }

    private func configureButton() {
        guard let button = statusItem.button else { return }
        button.image = MenubarIconRenderer.makeXRLabel()
        button.imagePosition = .imageOnly
    }

    private func buildMenu() -> NSMenu {
        let menu = NSMenu()

        let showWidget = NSMenuItem(
            title: "Show widget", action: #selector(toggleWidget), keyEquivalent: "\r"
        )
        showWidget.keyEquivalentModifierMask = [.shift, .command]
        showWidget.target = self
        menu.addItem(showWidget)

        statusMenuItem.title = status.primaryText
        statusMenuItem.isEnabled = false
        menu.addItem(statusMenuItem)

        menu.addItem(.separator())

        let detect = NSMenuItem(title: "Detect", action: #selector(detect), keyEquivalent: "d")
        detect.keyEquivalentModifierMask = [.command]
        detect.target = self
        menu.addItem(detect)

        let annotate = NSMenuItem(
            title: "Annotate", action: #selector(annotate), keyEquivalent: "a"
        )
        annotate.keyEquivalentModifierMask = [.shift, .command]
        annotate.target = self
        menu.addItem(annotate)

        menu.addItem(.separator())

        let settings = NSMenuItem(
            title: "Settings", action: #selector(openSettings), keyEquivalent: "s"
        )
        settings.keyEquivalentModifierMask = [.command]
        settings.target = self
        menu.addItem(settings)

        menu.addItem(.separator())

        let quit = NSMenuItem(
            title: "Quit",
            action: #selector(NSApplication.terminate(_:)),
            keyEquivalent: "q"
        )
        let powerIcon = NSImage(systemSymbolName: "power", accessibilityDescription: "Quit")
        powerIcon?.isTemplate = true
        quit.image = powerIcon
        menu.addItem(quit)
        return menu
    }

    @objc private func toggleWidget() { onToggleWidget?() }
    @objc private func detect() { onDetect?() }
    @objc private func annotate() { onAnnotate?() }
    @objc private func openSettings() { onSettings?() }
}
