import AppKit

/// Borderless-окно оверлея на один монитор: замороженный скриншот фоном +
/// `BboxCanvasView` поверх. Уровень `.screenSaver` — над всеми обычными окнами
/// и нашим floating-виджетом. Перехватывает все клики и клавиатуру (Esc/hotkeys).
final class OverlayWindow: NSWindow {
    let canvas: BboxCanvasView

    init(snapshot: DisplaySnapshot) {
        canvas = BboxCanvasView(monitorIndex: snapshot.monitorIndex)

        super.init(
            contentRect: snapshot.frame,
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        level = .screenSaver
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        ignoresMouseEvents = false
        collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]
        setFrame(snapshot.frame, display: false)

        let container = NSView(frame: NSRect(origin: .zero, size: snapshot.frame.size))
        container.wantsLayer = true

        let imageView = NSImageView(frame: container.bounds)
        imageView.image = NSImage(cgImage: snapshot.image, size: snapshot.frame.size)
        imageView.imageScaling = .scaleAxesIndependently
        imageView.autoresizingMask = [.width, .height]
        container.addSubview(imageView)

        canvas.frame = container.bounds
        canvas.autoresizingMask = [.width, .height]
        container.addSubview(canvas)

        contentView = container
    }

    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}
