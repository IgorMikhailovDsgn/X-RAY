import Foundation

/// Причина невалидности bbox (для подсветки на оверлее и в плашке координат).
enum ValidationError: Equatable {
    case tooSmall          // < 10×10
    case tumorOutsideRegion
    case tumorOverlap
}

/// Геометрическая валидация разметки из `docs/brainscan_annotation_mode.md`.
/// Чистая функция: получает состояние Region/Tumor, возвращает карту
/// `bboxId → первая найденная ошибка`. Send доступен, когда карта пуста.
enum ValidationEngine {
    static let minSide: CGFloat = 10

    static func validate(region: EntityState, tumor: EntityState) -> [UUID: ValidationError] {
        var errors: [UUID: ValidationError] = [:]

        let regions = region.bboxes
        let tumors = tumor.bboxes

        // 1. Минимальный размер — и для region, и для tumor.
        for box in regions + tumors where box.rect.width < minSide || box.rect.height < minSide {
            errors[box.id] = .tooSmall
        }

        // 2. Tumor должен лежать внутри какого-либо region на том же мониторе.
        for t in tumors where errors[t.id] == nil {
            let containedByRegion = regions.contains {
                $0.monitorIndex == t.monitorIndex && $0.rect.contains(t.rect)
            }
            if !containedByRegion {
                errors[t.id] = .tumorOutsideRegion
            }
        }

        // 3. Пересечение tumor-tumor на одном мониторе → оба невалидны.
        for i in tumors.indices {
            for j in tumors.indices where j > i {
                let a = tumors[i], b = tumors[j]
                guard a.monitorIndex == b.monitorIndex else { continue }
                if a.rect.intersects(b.rect) {
                    if errors[a.id] == nil { errors[a.id] = .tumorOverlap }
                    if errors[b.id] == nil { errors[b.id] = .tumorOverlap }
                }
            }
        }

        return errors
    }
}
