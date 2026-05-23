import AppKit

/// Borderless-окно detect-оверлея на один монитор: прозрачное окно поверх живого
/// экрана с `DetectOverlayView` (скрим + HUD + предсказания). Уровень `.screenSaver`,
/// как у оверлея разметки. Кликов не перехватывает по содержимому (read-only),
/// но ловит мышь, чтобы под ним не «протыкались» другие окна.
final class DetectOverlayWindow: NSWindow {
    let overlayView: DetectOverlayView

    init(frame: NSRect, isMain: Bool) {
        overlayView = DetectOverlayView(isMain: isMain, frame: NSRect(origin: .zero, size: frame.size))

        super.init(contentRect: frame, styleMask: [.borderless], backing: .buffered, defer: false)
        level = .screenSaver
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        ignoresMouseEvents = false  // нужен клик по Discard-тексту в HUD главного монитора
        collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]
        setFrame(frame, display: false)

        overlayView.autoresizingMask = [.width, .height]
        contentView = overlayView
    }
}
