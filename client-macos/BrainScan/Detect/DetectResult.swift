import AppKit

/// Один регион детекции + опц. опухоль. `regionDetectionId` всегда заполнен,
/// когда регион действительно нашла модель (в проде так и есть). Phase 10
/// клиент использует эти ID при последующем Approve/Edit через batch-эндпоинт
/// `/detect/annotations` — сервер по `detection_id` подтянет исходный bbox и
/// посчитает correction_type.
struct DetectedRegion: Equatable {
    let region: Bbox
    let regionDetectionId: UUID
    let tumor: Bbox?
    let tumorDetectionId: UUID?
}

/// Предсказания автодетекции для одного монитора.
struct DetectPrediction {
    let monitorIndex: Int
    let regions: [DetectedRegion]
}

/// Результат сессии автодетекции по всем мониторам.
struct DetectResult {
    /// `screenId` — id того screenshot row, по которому шёл `/detect`. Phase 10
    /// Edit/Approve переиспользует его (не делает повторного capture).
    let screenId: UUID?
    let predictions: [DetectPrediction]

    var hasAnyRegion: Bool { predictions.contains { !$0.regions.isEmpty } }

    /// Список всех bbox региона по всем мониторам (для overlay-рендера).
    var allRegionBboxes: [Bbox] { predictions.flatMap { p in p.regions.map(\.region) } }

    /// Список всех bbox опухолей (для overlay-рендера).
    var allTumorBboxes: [Bbox] {
        predictions.flatMap { p in p.regions.compactMap(\.tumor) }
    }

    /// Предзаполнение Region/Tumor для входа в Edit (см. спеку «Вход через Edit»).
    /// `originalDetectionId` каждого Bbox пробрасывается из DetectedRegion'а —
    /// AnnotationModel хранит его per-entity и при Send'е знает, какие detection_id
    /// привязывать к bbox / dismissed-списку.
    func prefillStates() -> (region: EntityState, tumor: EntityState) {
        var regions: [Bbox] = []
        var tumors: [Bbox] = []
        for p in predictions {
            for d in p.regions {
                regions.append(
                    Bbox(
                        id: d.region.id,
                        rect: d.region.rect,
                        monitorIndex: d.region.monitorIndex,
                        originalDetectionId: d.regionDetectionId
                    )
                )
                if let t = d.tumor, let tid = d.tumorDetectionId {
                    tumors.append(
                        Bbox(
                            id: t.id,
                            rect: t.rect,
                            monitorIndex: t.monitorIndex,
                            originalDetectionId: tid
                        )
                    )
                }
            }
        }
        let regionState: EntityState = regions.isEmpty ? .null : .bboxes(regions)
        let tumorState: EntityState = tumors.isEmpty ? .null : .bboxes(tumors)
        return (regionState, tumorState)
    }
}

/// Мок автодетекции — оставлен на случай отладочного режима без сервера.
/// detection_id заполняется фиксированным UUID, чтобы код, ожидающий его,
/// продолжал работать; в реальности эти ID никуда дальше не уходят.
enum MockDetector {
    private static var callCount = 0

    static func run(monitorIndex: Int, screenSize: CGSize) -> DetectResult {
        defer { callCount += 1 }
        let findsRegion = callCount % 2 == 0
        guard findsRegion else {
            return DetectResult(
                screenId: nil,
                predictions: [DetectPrediction(monitorIndex: monitorIndex, regions: [])]
            )
        }
        let regionSize = CGSize(width: min(440, screenSize.width * 0.4),
                                height: min(340, screenSize.height * 0.4))
        let regionRect = CGRect(
            x: (screenSize.width - regionSize.width) / 2,
            y: (screenSize.height - regionSize.height) / 2,
            width: regionSize.width, height: regionSize.height
        )
        let tumorRect = CGRect(x: regionRect.midX - 60, y: regionRect.midY - 50,
                               width: 120, height: 100)
        let detected = DetectedRegion(
            region: Bbox(rect: regionRect, monitorIndex: monitorIndex),
            regionDetectionId: UUID(),
            tumor: Bbox(rect: tumorRect, monitorIndex: monitorIndex),
            tumorDetectionId: UUID()
        )
        return DetectResult(
            screenId: nil,
            predictions: [DetectPrediction(monitorIndex: monitorIndex, regions: [detected])]
        )
    }
}
