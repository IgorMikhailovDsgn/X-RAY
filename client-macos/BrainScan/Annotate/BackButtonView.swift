import AppKit

/// Горизонтальная кнопка Back: круглая иконка (белый круг с тёмным шевроном —
/// asset `icon-back`, рендерится как есть, без template) + лейбл «Back».
/// Весь блок: opacity 70% по умолчанию, 100% при hover.
final class BackButtonView: NSView {
    var onClick: (() -> Void)?

    private let iconView = NSImageView()
    private let labelView = NSTextField(labelWithString: "Back")
    private var trackingArea: NSTrackingArea?
    private var hovered = false { didSet { applyState() } }

    override init(frame frameRect: NSRect) {
        super.init(frame: NSRect(x: 0, y: 0, width: 92, height: 64))
        wantsLayer = true

        iconView.image = NSImage(named: "icon-back")   // НЕ template — сохраняем цвета
        iconView.imageScaling = .scaleProportionallyUpOrDown
        iconView.translatesAutoresizingMaskIntoConstraints = false
        addSubview(iconView)

        labelView.font = .systemFont(ofSize: 12, weight: .medium)
        labelView.textColor = WidgetPalette.labelActive
        labelView.translatesAutoresizingMaskIntoConstraints = false
        addSubview(labelView)

        NSLayoutConstraint.activate([
            iconView.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            iconView.centerYAnchor.constraint(equalTo: centerYAnchor),
            iconView.widthAnchor.constraint(equalToConstant: 22),
            iconView.heightAnchor.constraint(equalToConstant: 22),
            labelView.leadingAnchor.constraint(equalTo: iconView.trailingAnchor, constant: 10),
            labelView.centerYAnchor.constraint(equalTo: centerYAnchor),
            labelView.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -12),
        ])
        applyState()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let trackingArea { removeTrackingArea(trackingArea) }
        let area = NSTrackingArea(rect: bounds,
                                  options: [.mouseEnteredAndExited, .activeAlways],
                                  owner: self, userInfo: nil)
        addTrackingArea(area)
        trackingArea = area
    }

    override func resetCursorRects() {
        super.resetCursorRects()
        addCursorRect(bounds, cursor: .pointingHand)
    }

    override func mouseEntered(with _: NSEvent) { hovered = true }
    override func mouseExited(with _: NSEvent) { hovered = false }
    override func mouseUp(with _: NSEvent) { onClick?() }

    private func applyState() {
        alphaValue = hovered ? 1.0 : 0.70   // иконка + лейбл одновременно
    }
}
