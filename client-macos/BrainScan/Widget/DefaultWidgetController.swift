import AppKit

/// Один NSPanel с combined view: indicator + widget body + dot + drag handles.
/// При смене статуса indicator меняет высоту → ресайзим панель сохраняя позицию
/// нижнего-левого угла (widget body остаётся на месте).
final class DefaultWidgetController {
    var onAnnotateClicked: (() -> Void)?
    var onDetectClicked: (() -> Void)?
    var onSettingsClicked: (() -> Void)?

    private let panel: NSPanel
    private let widgetView = DefaultWidgetView()

    private(set) var status: WidgetStatus {
        didSet { render() }
    }

    init(initialStatus: WidgetStatus = .noServer(localAnnotations: 0)) {
        self.status = initialStatus

        let initialSize = widgetView.totalSize()
        let panel = NSPanel(
            contentRect: NSRect(origin: .zero, size: initialSize),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]
        panel.isMovableByWindowBackground = true
        panel.hasShadow = false   // shadow рисуем сами на CALayer'ах
        panel.contentView = widgetView
        self.panel = panel

        wireActions()
        render()
    }

    // MARK: - Lifecycle

    func show() {
        if !panel.isVisible {
            positionAtDefaultLocation()
        }
        panel.orderFrontRegardless()
    }

    func hide() {
        panel.orderOut(nil)
    }

    var isVisible: Bool { panel.isVisible }

    func toggle() {
        isVisible ? hide() : show()
    }

    func setStatus(_ newStatus: WidgetStatus) {
        status = newStatus
    }

    // MARK: - Internals

    private func wireActions() {
        widgetView.closeButton.onClick = { [weak self] in self?.hide() }
        widgetView.annotateButton.onClick = { [weak self] in self?.onAnnotateClicked?() }
        widgetView.detectButton.onClick = { [weak self] in self?.onDetectClicked?() }
        widgetView.settingsButton.onClick = { [weak self] in self?.onSettingsClicked?() }
    }

    private func render() {
        widgetView.apply(status)
        // После apply indicator пересчитал свою высоту → меняем размер панели,
        // сохраняя origin (= bottom-left). Widget body таким образом не сдвигается.
        let newSize = widgetView.totalSize()
        let currentFrame = panel.frame
        let newFrame = NSRect(
            x: currentFrame.minX,
            y: currentFrame.minY,
            width: newSize.width,
            height: newSize.height
        )
        if newFrame.size != currentFrame.size {
            panel.setFrame(newFrame, display: true)
        }
        widgetView.needsLayout = true
        widgetView.layoutSubtreeIfNeeded()
    }

    private func positionAtDefaultLocation() {
        guard let screen = NSScreen.main else { return }
        let visible = screen.visibleFrame
        let margin: CGFloat = 24
        let size = panel.frame.size
        let origin = NSPoint(
            x: visible.maxX - size.width - margin,
            y: visible.minY + margin
        )
        panel.setFrameOrigin(origin)
    }
}
