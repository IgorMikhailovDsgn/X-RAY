import Foundation

/// Один bbox разметки. `rect` — в logical-точках в системе координат конкретного
/// дисплея (origin в его верхнем-левом углу, y растёт вниз — UI-семантика).
/// `monitorIndex` — индекс дисплея, на котором нарисован bbox; нужен для записи
/// в БД и конвертации в physical-пиксели этого монитора.
struct Bbox: Identifiable, Equatable {
    let id: UUID
    var rect: CGRect
    var monitorIndex: Int

    init(id: UUID = UUID(), rect: CGRect, monitorIndex: Int) {
        self.id = id
        self.rect = rect
        self.monitorIndex = monitorIndex
    }
}

/// Состояние одной сущности (Region или Tumor) из спеки annotation-mode.
/// `.bboxes` всегда непустой — пустой массив схлопывается в `.empty` на уровне модели.
enum EntityState: Equatable {
    case empty
    case null
    case bboxes([Bbox])

    var bboxes: [Bbox] {
        if case let .bboxes(list) = self { return list }
        return []
    }

    /// Сущность «определена» (bbox или null) — критерий для доступности Send.
    var isDefined: Bool {
        switch self {
        case .empty: return false
        case .null, .bboxes: return true
        }
    }

    var isNull: Bool {
        if case .null = self { return true }
        return false
    }
}
