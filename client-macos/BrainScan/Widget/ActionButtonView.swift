import AppKit

/// Item-кнопка из Figma «Button states» (3:173) с правками пользователя:
/// 72×64, icon ↔ label gap 8px, label `#FFFFFF` 70% default / 100% active,
/// active фон — `WidgetPalette.itemActiveBackground`.
final class ActionButtonView: NSView {
    enum VisualState: Equatable {
        case `default`
        case active
        case disabled
    }

    private let icon: Icon24
    private let label: String
    /// Иконка всегда 100% (в default и active). Лейбл при этом по-прежнему 70%→100%.
    /// disabled всё равно гасит иконку. Нужно для тулбара Annotate.
    private let iconAlwaysOpaque: Bool
    private let iconView = NSImageView()
    private let labelView = NSTextField(labelWithString: "")
    private let backgroundLayer = CALayer()
    private var trackingArea: NSTrackingArea?
    private(set) var state: VisualState = .default {
        didSet {
            applyState()
            // Курсор pointer только для enabled — переcбрасываем cursor rects при смене.
            window?.invalidateCursorRects(for: self)
        }
    }

    var onClick: (() -> Void)?

    init(
        icon: Icon24,
        label: String,
        enabled: Bool = true,
        tooltip: String? = nil,
        iconSize: CGFloat = 28,
        iconAlwaysOpaque: Bool = false
    ) {
        self.icon = icon
        self.label = label
        self.iconAlwaysOpaque = iconAlwaysOpaque
        super.init(frame: NSRect(x: 0, y: 0, width: 72, height: 64))
        wantsLayer = true
        layer?.addSublayer(backgroundLayer)
        backgroundLayer.cornerRadius = WidgetPalette.itemCornerRadius

        iconView.image = icon.makeImage(pointSize: iconSize - 2)
        iconView.contentTintColor = WidgetPalette.labelActive
        iconView.imageScaling = .scaleProportionallyUpOrDown
        iconView.translatesAutoresizingMaskIntoConstraints = false
        addSubview(iconView)

        let hasLabel = !label.isEmpty
        labelView.stringValue = label
        labelView.font = .systemFont(ofSize: 12, weight: .medium)
        labelView.textColor = WidgetPalette.labelDefault
        labelView.alignment = .center
        labelView.translatesAutoresizingMaskIntoConstraints = false
        labelView.isHidden = !hasLabel
        addSubview(labelView)

        if hasLabel {
            // С лейблом — icon сверху + label снизу, gap 8.
            NSLayoutConstraint.activate([
                iconView.topAnchor.constraint(equalTo: topAnchor, constant: 8),
                iconView.centerXAnchor.constraint(equalTo: centerXAnchor),
                iconView.widthAnchor.constraint(equalToConstant: iconSize),
                iconView.heightAnchor.constraint(equalToConstant: iconSize),
                labelView.topAnchor.constraint(equalTo: iconView.bottomAnchor, constant: 8),
                labelView.leadingAnchor.constraint(equalTo: leadingAnchor),
                labelView.trailingAnchor.constraint(equalTo: trailingAnchor),
            ])
        } else {
            // Без лейбла (close-кнопка) — иконка по центру.
            NSLayoutConstraint.activate([
                iconView.centerXAnchor.constraint(equalTo: centerXAnchor),
                iconView.centerYAnchor.constraint(equalTo: centerYAnchor),
                iconView.widthAnchor.constraint(equalToConstant: iconSize),
                iconView.heightAnchor.constraint(equalToConstant: iconSize),
            ])
        }

        toolTip = tooltip
        state = enabled ? .default : .disabled
        applyState()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    override func layout() {
        super.layout()
        backgroundLayer.frame = bounds
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let trackingArea {
            removeTrackingArea(trackingArea)
        }
        // .activeAlways — приложение никогда не становится active
        // (NSPanel с .nonactivatingPanel), .activeInActiveApp ничего бы не дал.
        let area = NSTrackingArea(
            rect: bounds,
            options: [.mouseEnteredAndExited, .activeAlways],
            owner: self,
            userInfo: nil
        )
        addTrackingArea(area)
        trackingArea = area
    }

    override func resetCursorRects() {
        super.resetCursorRects()
        if state != .disabled {
            addCursorRect(bounds, cursor: .pointingHand)
        }
    }

    override func mouseEntered(with _: NSEvent) {
        guard state != .disabled else { return }
        state = .active
    }

    override func mouseExited(with _: NSEvent) {
        guard state != .disabled else { return }
        state = .default
    }

    override func mouseUp(with _: NSEvent) {
        guard state != .disabled else { return }
        onClick?()
    }

    func setEnabled(_ enabled: Bool) {
        state = enabled ? .default : .disabled
    }

    private func applyState() {
        switch state {
        case .default:
            backgroundLayer.backgroundColor = NSColor.clear.cgColor
            labelView.textColor = WidgetPalette.labelDefault
            iconView.alphaValue = iconAlwaysOpaque ? 1.0 : 0.70
        case .active:
            backgroundLayer.backgroundColor = WidgetPalette.itemActiveBackground.cgColor
            labelView.textColor = WidgetPalette.labelActive
            iconView.alphaValue = 1.0
        case .disabled:
            backgroundLayer.backgroundColor = NSColor.clear.cgColor
            labelView.textColor = WidgetPalette.labelDefault.withAlphaComponent(0.35)
            iconView.alphaValue = 0.35
        }
    }
}
