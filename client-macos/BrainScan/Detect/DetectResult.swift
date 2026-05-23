import AppKit

/// Предсказание автодетекции для одного монитора. `region`/`tumor` = nil означает
/// «модель не нашла» (→ null при предзаполнении Edit). `detectionId` нужен для
/// action-маппинга на бэкенде (confirmed/corrected) — пробрасывается при Send.
struct DetectPrediction {
    let monitorIndex: Int
    let region: Bbox?
    let regionDetectionId: UUID?
    let tumor: Bbox?
    let tumorDetectionId: UUID?
}

/// Результат сессии автодетекции по всем мониторам.
struct DetectResult {
    let predictions: [DetectPrediction]

    var hasAnyRegion: Bool { predictions.contains { $0.region != nil } }

    /// Предзаполнение Region/Tumor для входа в Edit (см. спеку «Вход через Edit»).
    /// Нет region → оба null (каскад). Нет tumor при наличии region → tumor null.
    func prefillStates() -> (region: EntityState, tumor: EntityState) {
        let regionBoxes = predictions.compactMap { $0.region }
        guard !regionBoxes.isEmpty else { return (.null, .null) }
        let tumorBoxes = predictions.compactMap { $0.tumor }
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
                DetectPrediction(monitorIndex: monitorIndex, region: nil,
                                 regionDetectionId: UUID(), tumor: nil, tumorDetectionId: nil)
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
                region: Bbox(rect: regionRect, monitorIndex: monitorIndex),
                regionDetectionId: UUID(),
                tumor: Bbox(rect: tumorRect, monitorIndex: monitorIndex),
                tumorDetectionId: UUID()
            )
        ])
    }
}
