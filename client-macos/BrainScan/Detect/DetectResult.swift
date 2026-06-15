import AppKit

/// Предсказания автодетекции для одного монитора. Пустые массивы означают
/// «модель не нашла» (→ null при предзаполнении Edit, кнопка Region NULL/
/// Tumor NULL в тулбаре). `tumors` параллелен `regions` по индексу опухолям,
/// которые сервер нашёл хоть в одном из регионов — но nil-tumor-регионы
/// сервер отдаёт без записи в `tumors`, так что массивы не выравнены 1:1.
/// Координаты — top-left logical, как у всех overlay-канвасов (isFlipped=true).
struct DetectPrediction {
    let monitorIndex: Int
    let regions: [Bbox]
    let tumors: [Bbox]
}

/// Результат сессии автодетекции по всем мониторам.
struct DetectResult {
    let predictions: [DetectPrediction]

    var hasAnyRegion: Bool { predictions.contains { !$0.regions.isEmpty } }

    /// Предзаполнение Region/Tumor для входа в Edit (см. спеку «Вход через Edit»).
    /// Нет региона → оба null (каскад). Нет опухоли при наличии региона → tumor null.
    func prefillStates() -> (region: EntityState, tumor: EntityState) {
        let regionBoxes = predictions.flatMap { $0.regions }
        guard !regionBoxes.isEmpty else { return (.null, .null) }
        let tumorBoxes = predictions.flatMap { $0.tumors }
        return (.bboxes(regionBoxes), tumorBoxes.isEmpty ? .null : .bboxes(tumorBoxes))
    }
}

/// Мок автодетекции, пока реальный `/detect` отдаёт 503. Чередует «нашёл» и
/// «не нашёл» при каждом вызове, чтобы можно было проверить оба состояния UI.
enum MockDetector {
    private static var callCount = 0

    static func run(monitorIndex: Int, screenSize: CGSize) -> DetectResult {
        defer { callCount += 1 }
        let findsRegion = callCount % 2 == 0
        guard findsRegion else {
            return DetectResult(predictions: [
                DetectPrediction(monitorIndex: monitorIndex, regions: [], tumors: [])
            ])
        }
        // Region по центру, tumor вложен внутрь — координаты в logical-точках монитора.
        let regionSize = CGSize(width: min(440, screenSize.width * 0.4),
                                height: min(340, screenSize.height * 0.4))
        let regionRect = CGRect(
            x: (screenSize.width - regionSize.width) / 2,
            y: (screenSize.height - regionSize.height) / 2,
            width: regionSize.width, height: regionSize.height
        )
        let tumorRect = CGRect(x: regionRect.midX - 60, y: regionRect.midY - 50,
                               width: 120, height: 100)
        return DetectResult(predictions: [
            DetectPrediction(
                monitorIndex: monitorIndex,
                regions: [Bbox(rect: regionRect, monitorIndex: monitorIndex)],
                tumors: [Bbox(rect: tumorRect, monitorIndex: monitorIndex)]
            )
        ])
    }
}
