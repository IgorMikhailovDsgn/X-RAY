import AppKit

/// Показывает короткое уведомление-плашку (`ToastView`) в floating-панели рядом
/// с виджетом. Один тост одновременно — повторный вызов перезаписывает текущий.
@MainActor
final class ToastController {
    static let shared = ToastController()

    private var panel: NSPanel?
    private var hideWork: DispatchWorkItem?

    private let showDuration: TimeInterval = 2.5
    private let fadeIn: TimeInterval = 0.18
    private let fadeOut: TimeInterval = 0.3
    private let verticalOffset: CGFloat = 64   // над верхней кромкой widget body

    /// Показать тост `text` с `icon` (tinted в `iconTint`) над `near` (центр тела
    /// виджета в экранных координатах).
    func show(text: String, icon: NSImage?, iconTint: NSColor, near point: NSPoint) {
        hideWork?.cancel()
        panel?.orderOut(nil)

        let view = ToastView(icon: icon, iconTint: iconTint, text: text)
        view.translatesAutoresizingMaskIntoConstraints = false
        view.layoutSubtreeIfNeeded()
        let size = view.fittingSize

        let panel = NSPanel(
            contentRect: NSRect(origin: .zero, size: size),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered, defer: false
        )
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]
        panel.contentView = view

        let origin = NSPoint(x: point.x - size.width / 2, y: point.y + verticalOffset)
        panel.setFrame(NSRect(origin: origin, size: size), display: true)
        panel.alphaValue = 0
        panel.orderFrontRegardless()

        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = fadeIn
            ctx.allowsImplicitAnimation = true
            panel.animator().alphaValue = 1.0
        }

        self.panel = panel
        let work = DispatchWorkItem { [weak self, weak panel] in
            guard let panel else { return }
            NSAnimationContext.runAnimationGroup({ ctx in
                ctx.duration = self?.fadeOut ?? 0.3
                panel.animator().alphaValue = 0
            }, completionHandler: {
                panel.orderOut(nil)
            })
            if self?.panel === panel { self?.panel = nil }
        }
        hideWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + showDuration, execute: work)
    }
}
