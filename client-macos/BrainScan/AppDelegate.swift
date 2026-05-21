import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var menubar: MenubarController?
    private var widget: DefaultWidgetController?
    private let settings = SettingsWindowController()
    private let annotate = AnnotateController()

    func applicationDidFinishLaunching(_: Notification) {
        let widget = DefaultWidgetController()
        widget.onAnnotateClicked = { [weak self] in self?.handleAnnotate() }
        widget.onDetectClicked = { [weak self] in self?.handleDetect() }
        widget.onSettingsClicked = { [weak self] in self?.handleSettings() }
        widget.show()
        self.widget = widget

        let menubar = MenubarController()
        menubar.onToggleWidget = { [weak widget] in widget?.toggle() }
        menubar.onAnnotate = { [weak self] in self?.handleAnnotate() }
        menubar.onDetect = { [weak self] in self?.handleDetect() }
        menubar.onSettings = { [weak self] in self?.handleSettings() }
        self.menubar = menubar

        annotate.onFinished = { [weak self] bodyCenter in
            self?.widget?.place(bodyCenter: bodyCenter)
            self?.widget?.show()
        }
    }

    private func handleAnnotate() {
        guard let widget else { return }
        let center = widget.bodyCenterOnScreen
        widget.hide()
        annotate.start(bodyCenter: center)
    }

    private func handleDetect() {
        // MVP: Detect задизаблен пока нет моделей; ручка остаётся для будущего.
    }

    private func handleSettings() {
        settings.present()
    }
}
