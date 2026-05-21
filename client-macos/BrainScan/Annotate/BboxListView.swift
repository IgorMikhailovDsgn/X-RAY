import AppKit

/// Содержимое выпадающего списка: вертикальный стек плашек координат (по одной
/// на bbox сущности). Плавает над тулбаром в отдельной панели. Клик по плашке
/// выбирает bbox, × удаляет, наведение даёт двустороннюю подсветку с оверлеем.
final class BboxListView: NSView {
    var onSelect: ((UUID) -> Void)?
    var onRemove: ((UUID) -> Void)?
    var onHover: ((UUID?) -> Void)?

    static let plateWidth: CGFloat = 126
    static let plateHeight: CGFloat = 56
    static let spacing: CGFloat = 8

    private let stack = NSStackView()
    private var plates: [CoordinatePlateView] = []

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = Self.spacing
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: trailingAnchor),
            stack.topAnchor.constraint(equalTo: topAnchor),
            stack.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    /// Перестроить список под текущие bbox. Порядок — сверху вниз по индексу.
    func setItems(_ boxes: [Bbox], activeId: UUID?, hoveredId: UUID?,
                  invalid: [UUID: ValidationError]) {
        for v in stack.arrangedSubviews {
            stack.removeArrangedSubview(v); v.removeFromSuperview()
        }
        plates.removeAll()

        for box in boxes {
            let plate = CoordinatePlateView()
            plate.style = .card
            plate.bboxId = box.id
            plate.configure(rect: box.rect, isActive: box.id == activeId,
                            isInvalid: invalid[box.id] != nil, showsClear: true)
            plate.setExternallyLit(box.id == hoveredId)
            plate.onSelect = { [weak self] in self?.onSelect?(box.id) }
            plate.onClear = { [weak self] in self?.onRemove?(box.id) }
            plate.onHover = { [weak self] id in self?.onHover?(id) }
            plate.translatesAutoresizingMaskIntoConstraints = false
            NSLayoutConstraint.activate([
                plate.widthAnchor.constraint(equalToConstant: Self.plateWidth),
                plate.heightAnchor.constraint(equalToConstant: Self.plateHeight),
            ])
            stack.addArrangedSubview(plate)
            plates.append(plate)
        }
    }

    /// Освежить только подсветку (без перестройки), когда меняется hovered/active.
    func updateHighlight(activeId: UUID?, hoveredId: UUID?) {
        for plate in plates {
            plate.setExternallyLit(plate.bboxId == hoveredId)
        }
    }

    func fittingHeight(count: Int) -> CGFloat {
        guard count > 0 else { return 0 }
        return CGFloat(count) * Self.plateHeight + CGFloat(count - 1) * Self.spacing
    }
}
