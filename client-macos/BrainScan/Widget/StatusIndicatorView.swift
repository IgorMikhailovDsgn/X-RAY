import AppKit

/// «Шапка» над виджетом: точка статуса + main-текст + опц. ⓘ + вторичные строки.
/// Дизайн взят из Figma «Matrix of widget's status» (36:1843) — индикатор-блок
/// над каждым из 5 состояний.
///
/// Все ряды собраны в hStack/vStack с trailing-якорями, чтобы `fittingSize`
/// возвращал реальную ширину контента (нужно для hug-поведения родителя).
final class StatusIndicatorView: NSView {
    var onHoverEnter: (() -> Void)?
    var onHoverExit: (() -> Void)?

    private let dotView = NSView()
    private let primaryLabel = NSTextField(labelWithString: "")
    private let warningIcon = NSImageView()
    private let topRowStack = NSStackView()
    private let secondaryStack = NSStackView()
    private var trackingArea: NSTrackingArea?

    private var dotLayer: CALayer { dotView.layer! }

    init() {
        super.init(frame: .zero)
        wantsLayer = true
        layer?.backgroundColor = WidgetPalette.outerBackground.cgColor
        layer?.cornerRadius = WidgetPalette.outerCornerRadius

        dotView.wantsLayer = true
        dotLayer.cornerRadius = 3
        dotView.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            dotView.widthAnchor.constraint(equalToConstant: 6),
            dotView.heightAnchor.constraint(equalToConstant: 6),
        ])

        primaryLabel.font = .systemFont(ofSize: 12, weight: .semibold)
        primaryLabel.textColor = WidgetPalette.labelActive
        primaryLabel.lineBreakMode = .byClipping
        primaryLabel.setContentCompressionResistancePriority(.required, for: .horizontal)
        primaryLabel.setContentHuggingPriority(.required, for: .horizontal)

        warningIcon.image = NSImage(
            systemSymbolName: "exclamationmark.circle",
            accessibilityDescription: "Warning"
        )
        warningIcon.contentTintColor = WidgetPalette.labelActive
        warningIcon.translatesAutoresizingMaskIntoConstraints = false
        warningIcon.isHidden = true
        NSLayoutConstraint.activate([
            warningIcon.widthAnchor.constraint(equalToConstant: 14),
            warningIcon.heightAnchor.constraint(equalToConstant: 14),
        ])

        topRowStack.orientation = .horizontal
        topRowStack.alignment = .centerY
        topRowStack.spacing = 6
        topRowStack.translatesAutoresizingMaskIntoConstraints = false
        topRowStack.addArrangedSubview(dotView)
        topRowStack.addArrangedSubview(primaryLabel)
        topRowStack.setCustomSpacing(4, after: primaryLabel)
        topRowStack.addArrangedSubview(warningIcon)
        addSubview(topRowStack)

        secondaryStack.orientation = .vertical
        secondaryStack.alignment = .leading
        secondaryStack.spacing = 4
        secondaryStack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(secondaryStack)

        NSLayoutConstraint.activate([
            topRowStack.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            topRowStack.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -12),
            topRowStack.topAnchor.constraint(equalTo: topAnchor, constant: 12),

            secondaryStack.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            secondaryStack.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -12),
            secondaryStack.topAnchor.constraint(equalTo: topRowStack.bottomAnchor, constant: 8),
            secondaryStack.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -10),
        ])
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let trackingArea {
            removeTrackingArea(trackingArea)
        }
        let area = NSTrackingArea(
            rect: bounds,
            options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect],
            owner: self,
            userInfo: nil
        )
        addTrackingArea(area)
        trackingArea = area
    }

    override func mouseEntered(with _: NSEvent) { onHoverEnter?() }
    override func mouseExited(with _: NSEvent) { onHoverExit?() }

    func apply(_ status: WidgetStatus) {
        dotLayer.backgroundColor = status.dotColor.cgColor
        primaryLabel.stringValue = status.primaryText
        warningIcon.isHidden = !status.showsWarningGlyph

        secondaryStack.arrangedSubviews.forEach { $0.removeFromSuperview() }
        for line in status.secondaryLines {
            let label = NSTextField(labelWithString: line)
            label.font = .systemFont(ofSize: 12, weight: .regular)
            label.textColor = WidgetPalette.labelDefault
            label.lineBreakMode = .byWordWrapping
            label.maximumNumberOfLines = 0
            label.setContentHuggingPriority(.required, for: .horizontal)
            label.setContentCompressionResistancePriority(.required, for: .horizontal)
            secondaryStack.addArrangedSubview(label)
        }
        needsLayout = true
        invalidateIntrinsicContentSize()
    }
}
