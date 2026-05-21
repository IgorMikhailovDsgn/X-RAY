import Foundation

/// Заглушка отправки разметки. APIClient (Phase C step 3) ещё не реализован,
/// поэтому здесь собирается валидный payload в physical/crop-координатах и
/// логируется. Реальный upload в S3/API подключим, когда появится APIClient.
enum AnnotationSubmitter {
    struct RegionPayload { let bboxPhysical: CGRect?; let monitorIndex: Int; let isNull: Bool }
    struct TumorPayload { let bboxInCrop: CGRect?; let isNull: Bool }
    struct Payload { let regions: [RegionPayload]; let tumors: [TumorPayload] }

    /// Собрать payload из состояния модели и снапшотов мониторов (для dpi).
    static func makePayload(model: AnnotationModel,
                            snapshots: [Int: DisplaySnapshot]) -> Payload {
        func dpi(_ monitorIndex: Int) -> CGFloat {
            snapshots[monitorIndex]?.scaleFactor ?? 2.0
        }

        let regions: [RegionPayload]
        switch model.regionState {
        case .null:
            regions = [RegionPayload(bboxPhysical: nil, monitorIndex: 0, isNull: true)]
        case let .bboxes(list):
            regions = list.map {
                RegionPayload(
                    bboxPhysical: CoordinateConverter.physical($0.rect, dpi: dpi($0.monitorIndex)),
                    monitorIndex: $0.monitorIndex, isNull: false
                )
            }
        case .empty:
            regions = []
        }

        // Tumor конвертируется в crop первого региона (мульти-регион — TODO при APIClient).
        let regionRect = model.regionState.bboxes.first?.rect
        let regionMonitor = model.regionState.bboxes.first?.monitorIndex ?? 0
        let tumors: [TumorPayload]
        switch model.tumorState {
        case .null:
            tumors = [TumorPayload(bboxInCrop: nil, isNull: true)]
        case let .bboxes(list):
            tumors = list.map { t in
                let crop = regionRect.map {
                    CoordinateConverter.tumorInCrop(tumorLogical: t.rect, regionLogical: $0,
                                                    dpi: dpi(regionMonitor))
                }
                return TumorPayload(bboxInCrop: crop, isNull: false)
            }
        case .empty:
            tumors = []
        }

        return Payload(regions: regions, tumors: tumors)
    }

    static func submit(_ payload: Payload) {
        NSLog("[BrainScan] Annotation submit (stub): regions=\(payload.regions.count) "
              + "tumors=\(payload.tumors.count)")
        // TODO(APIClient): загрузить скриншот+crop в S3, создать localize/tumor annotations.
    }
}
