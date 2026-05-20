import AppKit

/// Combined-view: indicator card + widget body + status dot + drag handles —
/// всё в одном NSView (и, соответственно, в одном NSPanel),
/// чтобы indicator двигался вместе с виджетом при drag'е окна.
///
/// Layout (в координатах AppKit, y растёт вверх):
/// ```
/// ┌──── indicator card (right-aligned, hidden until hover) ──┐
/// │ ● Server Connected                                       │
/// │   Localizer: v1.4                                        │
/// │   Tumor Detector: v1.4                                   │
/// └──────────────────────────────────────────────────────────┘
///                                              ◯ ← StatusDotView (hover trigger)
/// ┌──── widget body (308×74) ────────────────────────────────┐
/// │ ╎ [×] | [Detect] [Annotate] | [Settings] ╎               │  ╎ = drag handles 3px
/// └──────────────────────────────────────────────────────────┘
/// ```
final class DefaultWidgetView: NSView {
    let closeButton: ActionButtonView
    let detectButton: ActionButtonView
    let annotateButton: ActionButtonView
    let settingsButton: ActionButtonView
    let indicatorView = StatusIndicatorView()

    private let outerLayer = CALayer()
    private let innerLayer = CALayer()
    private let leftSeparator = CALayer()
    private let rightSeparator = CALayer()
    private let statusDot = StatusDotView(frame: .zero)
    private let leftDragHandle = DragHandleView(frame: .zero)
    private let rightDragHandle = DragHandleView(frame: .zero)
    private var hideIndicatorWork: DispatchWorkItem?
    private let hideDelay: TimeInterval = 0.15

    private let widgetBodySize = CGSize(width: 308, height: 74)
    private let dotDiameter: CGFloat = 16
    private let dotOverflow: CGFloat = 8
    private let widgetIndicatorGap: CGFloat = 8
    private let dragHandleWidth: CGFloat = 3
    private let minIndicatorHeight: CGFloat = 36

    init() {
        closeButton = ActionButtonView(icon: .close, label: "", iconSize: 24)
        detectButton = ActionButtonView(
            icon: .detect, label: "Detect", enabled: false,
            tooltip: "Model not deployed"
        )
        annotateButton = ActionButtonView(icon: .annotate, label: "Annotate")
        settingsButton = ActionButtonView(icon: .settings, label: "Settings")

        super.init(frame: .zero)

        wantsLayer = true
        layer?.masksToBounds = false

        // Indicator card сверху. Скрыта по умолчанию — появляется при hover'е на dot.
        indicatorView.isHidden = true
        addSubview(indicatorView)

        // Widget body — layers.
        outerLayer.backgroundColor = WidgetPalette.outerBackground.cgColor
        outerLayer.cornerRadius = WidgetPalette.outerCornerRadius
        outerLayer.cornerCurve = .continuous   // «60% smoothing» — iOS-squircle
        outerLayer.masksToBounds = false
        layer?.addSublayer(outerLayer)

        innerLayer.backgroundColor = WidgetPalette.innerFill.cgColor
        innerLayer.cornerRadius = WidgetPalette.innerCornerRadius
        innerLayer.cornerCurve = .continuous
        innerLayer.borderWidth = 1   // inside-stroke
        innerLayer.borderColor = WidgetPalette.innerStroke.cgColor
        innerLayer.masksToBounds = true
        layer?.addSublayer(innerLayer)

        for sep in [leftSeparator, rightSeparator] {
            sep.backgroundColor = WidgetPalette.separator.cgColor
            layer?.addSublayer(sep)
        }

        addSubview(closeButton)
        addSubview(detectButton)
        addSubview(annotateButton)
        addSubview(settingsButton)

        // Drag-handles поверх (transparent, hit-test работает).
        addSubview(leftDragHandle)
        addSubview(rightDragHandle)

        // Status dot — NSView, опаковые пиксели → надёжный hover.
        addSubview(statusDot)
        statusDot.onHoverEnter = { [weak self] in self?.cancelHideAndShow() }
        statusDot.onHoverExit = { [weak self] in self?.scheduleHide() }
        indicatorView.onHoverEnter = { [weak self] in self?.cancelHideAndShow() }
        indicatorView.onHoverExit = { [weak self] in self?.scheduleHide() }

        // Continuous corners на indicator card.
        indicatorView.wantsLayer = true
        indicatorView.layer?.cornerCurve = .continuous

        frame = NSRect(origin: .zero, size: totalSize())
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    private func cancelHideAndShow() {
        hideIndicatorWork?.cancel()
        hideIndicatorWork = nil
        indicatorView.isHidden = false
    }

    private func scheduleHide() {
        hideIndicatorWork?.cancel()
        let work = DispatchWorkItem { [weak self] in
            self?.indicatorView.isHidden = true
        }
        hideIndicatorWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + hideDelay, execute: work)
    }

    /// Полный размер view = ширина (308 + dotOverflow), высота (body + gap + indicator).
    func totalSize() -> CGSize {
        let indicatorSize = currentIndicatorSize()
        return CGSize(
            width: widgetBodySize.width + dotOverflow,
            height: widgetBodySize.height + widgetIndicatorGap + indicatorSize.height
        )
    }

    /// Hug по содержимому: ширина и высота берутся из `fittingSize` StatusIndicatorView.
    private func currentIndicatorSize() -> CGSize {
        indicatorView.layoutSubtreeIfNeeded()
        let fit = indicatorView.fittingSize
        return CGSize(width: fit.width, height: max(fit.height, minIndicatorHeight))
    }

    override func layout() {
        super.layout()

        // Widget body — внизу слева, 308×74.
        let bodyRect = CGRect(origin: .zero, size: widgetBodySize)
        outerLayer.frame = bodyRect

        // Inner с 1px паддингом от outer + 1px inside-border.
        let innerRect = bodyRect.insetBy(dx: 1, dy: 1)
        innerLayer.frame = innerRect

        // Кнопки и разделители (координаты из Figma).
        let yButtons = innerRect.minY + 5
        closeButton.frame = NSRect(x: innerRect.minX + 12, y: yButtons, width: 32, height: 64)
        leftSeparator.frame = NSRect(
            x: innerRect.minX + 52, y: innerRect.minY + 17, width: 1, height: 38
        )
        detectButton.frame = NSRect(x: innerRect.minX + 61, y: yButtons, width: 72, height: 64)
        annotateButton.frame = NSRect(
            x: innerRect.minX + 141, y: yButtons, width: 72, height: 64
        )
        rightSeparator.frame = NSRect(
            x: innerRect.minX + 221, y: innerRect.minY + 17, width: 1, height: 38
        )
        settingsButton.frame = NSRect(
            x: innerRect.minX + 230, y: yButtons, width: 72, height: 64
        )

        // Drag-handles — 3px полосы по бокам widget body.
        leftDragHandle.frame = NSRect(
            x: bodyRect.minX, y: bodyRect.minY, width: dragHandleWidth, height: bodyRect.height
        )
        rightDragHandle.frame = NSRect(
            x: bodyRect.maxX - dragHandleWidth, y: bodyRect.minY,
            width: dragHandleWidth, height: bodyRect.height
        )

        // Status dot — центр на правом-верхнем углу widget body, half overflows наружу.
        let dotCenter = CGPoint(x: bodyRect.maxX - 2, y: bodyRect.maxY - 2)
        statusDot.frame = NSRect(
            x: dotCenter.x - dotDiameter / 2,
            y: dotCenter.y - dotDiameter / 2,
            width: dotDiameter,
            height: dotDiameter
        )

        // Indicator card — сверху над widget body, right-aligned к его правому краю.
        let indicatorSize = currentIndicatorSize()
        let indicatorY = bodyRect.maxY + widgetIndicatorGap
        let indicatorX = bodyRect.maxX - indicatorSize.width
        indicatorView.frame = NSRect(
            x: indicatorX, y: indicatorY,
            width: indicatorSize.width, height: indicatorSize.height
        )
    }

    func apply(_ status: WidgetStatus) {
        statusDot.fillColor = status.dotColor
        detectButton.setEnabled(status.isDetectEnabled)
        indicatorView.apply(status)
        needsLayout = true
    }
}
