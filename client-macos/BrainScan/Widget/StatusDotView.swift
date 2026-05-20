import AppKit

/// Зелёная (или красная/жёлтая) status-точка справа-сверху виджета.
///
/// Реализован как NSView с круглым layer'ом — опаковые пиксели гарантируют что
/// `NSPanel`'у есть за что зацепить per-pixel hit-test и мышь над dot'ом
/// надёжно триггерит mouseEntered. Невидимая HoverArea с alpha=0.01 в этой
/// связке оказалась нестабильной.
final class StatusDotView: NSView {
    var onHoverEnter: (() -> Void)?
    var onHoverExit: (() -> Void)?

    private var trackingArea: NSTrackingArea?
    private let fillLayer = CALayer()
    private let strokeLayer = CALayer()

    var fillColor: NSColor = WidgetPalette.statusDotFill {
        didSet { fillLayer.backgroundColor = fillColor.cgColor }
    }

    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        layer?.masksToBounds = false

        strokeLayer.backgroundColor = WidgetPalette.statusDotStroke.cgColor
        layer?.addSublayer(strokeLayer)

        fillLayer.backgroundColor = fillColor.cgColor
        layer?.addSublayer(fillLayer)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    override func layout() {
        super.layout()
        // strokeLayer = чуть больший круг, fill — внутри. Получается outside-stroke 1.5px.
        let inset: CGFloat = 1.5
        strokeLayer.frame = bounds
        strokeLayer.cornerRadius = bounds.width / 2
        fillLayer.frame = bounds.insetBy(dx: inset, dy: inset)
        fillLayer.cornerRadius = (bounds.width - 2 * inset) / 2
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let trackingArea {
            removeTrackingArea(trackingArea)
        }
        let area = NSTrackingArea(
            rect: bounds,
            options: [.mouseEnteredAndExited, .activeAlways],
            owner: self,
            userInfo: nil
        )
        addTrackingArea(area)
        trackingArea = area
    }

    override func mouseEntered(with _: NSEvent) { onHoverEnter?() }
    override func mouseExited(with _: NSEvent) { onHoverExit?() }
}
