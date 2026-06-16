import XCTest
@testable import BrainScan

final class AnnotationModelTests: XCTestCase {
    private func box(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat,
                     monitor: Int = 0) -> Bbox {
        Bbox(rect: CGRect(x: x, y: y, width: w, height: h), monitorIndex: monitor)
    }

    func test_cold_start_send_disabled_and_both_mark_null_visible() {
        let m = AnnotationModel()
        XCTAssertEqual(m.regionState, .empty)
        XCTAssertEqual(m.tumorState, .empty)
        XCTAssertFalse(m.sendEnabled)
        XCTAssertTrue(m.markNullRegionVisible)
        XCTAssertTrue(m.markNullTumorVisible)
        XCTAssertTrue(m.addTumorEnabled)
    }

    func test_mark_null_region_cascades_tumor_to_null_and_disables_tumor_controls() {
        let m = AnnotationModel()
        m.markNullRegion()
        XCTAssertTrue(m.regionState.isNull)
        XCTAssertTrue(m.tumorState.isNull)
        XCTAssertFalse(m.tumorControlsEnabled)
        XCTAssertFalse(m.addTumorEnabled)
        XCTAssertFalse(m.markNullTumorVisible)
        // Region=null + Tumor=null → обе определены, нет bbox → Send доступен.
        XCTAssertTrue(m.sendEnabled)
    }

    func test_region_bbox_plus_tumor_bbox_enables_send() {
        let m = AnnotationModel()
        m.appendRegionBbox(box(0, 0, 100, 100))
        XCTAssertFalse(m.markNullRegionVisible)   // есть bbox → Mark Null Region скрыт
        XCTAssertFalse(m.sendEnabled)             // tumor ещё empty
        m.appendTumorBbox(box(10, 10, 20, 20))
        XCTAssertTrue(m.sendEnabled)
    }

    func test_region_bbox_with_mark_null_tumor_enables_send() {
        let m = AnnotationModel()
        m.appendRegionBbox(box(0, 0, 100, 100))
        m.markNullTumor()
        XCTAssertTrue(m.tumorState.isNull)
        XCTAssertTrue(m.sendEnabled)
    }

    func test_clear_region_cascades_tumor_to_empty() {
        let m = AnnotationModel()
        m.appendRegionBbox(box(0, 0, 100, 100))
        m.appendTumorBbox(box(10, 10, 20, 20))
        m.clearRegion()
        XCTAssertEqual(m.regionState, .empty)
        XCTAssertEqual(m.tumorState, .empty)
        XCTAssertFalse(m.sendEnabled)
    }

    func test_remove_last_region_bbox_cascades_to_empty() {
        let m = AnnotationModel()
        let r = box(0, 0, 100, 100)
        m.appendRegionBbox(r)
        m.appendTumorBbox(box(10, 10, 20, 20))
        m.removeBbox(id: r.id)
        XCTAssertEqual(m.regionState, .empty)
        XCTAssertEqual(m.tumorState, .empty)   // каскад
    }

    func test_remove_one_of_two_region_bboxes_keeps_tumor() {
        let m = AnnotationModel()
        let r1 = box(0, 0, 100, 100)
        let r2 = box(200, 0, 100, 100)
        m.appendRegionBbox(r1)
        m.appendRegionBbox(r2)
        m.appendTumorBbox(box(10, 10, 20, 20))
        m.removeBbox(id: r1.id)
        XCTAssertEqual(m.regionState.bboxes.count, 1)
        XCTAssertEqual(m.tumorState.bboxes.count, 1)   // не каскадим, регион ещё есть
    }

    func test_add_tumor_blocked_when_region_null() {
        let m = AnnotationModel()
        m.markNullRegion()
        m.activateAddTumor()
        XCTAssertEqual(m.activeTool, .none)   // запрос проигнорирован
        m.appendTumorBbox(box(10, 10, 20, 20))
        XCTAssertTrue(m.tumorState.isNull)    // tumor остался null
    }

    func test_invalid_bbox_blocks_send() {
        let m = AnnotationModel()
        let r = box(0, 0, 100, 100)
        let t = box(10, 10, 20, 20)
        m.appendRegionBbox(r)
        m.appendTumorBbox(t)
        XCTAssertTrue(m.sendEnabled)
        m.invalidBboxIds = [t.id]
        XCTAssertFalse(m.sendEnabled)
    }

    func test_append_sets_per_entity_active_ids() {
        let m = AnnotationModel()
        let r = box(0, 0, 100, 100)
        let t = box(10, 10, 20, 20)
        m.appendRegionBbox(r)
        m.appendTumorBbox(t)
        XCTAssertEqual(m.activeRegionBbox?.id, r.id)
        XCTAssertEqual(m.activeTumorBbox?.id, t.id)
        XCTAssertEqual(m.activeRegionIndex, 1)
        XCTAssertEqual(m.activeTumorIndex, 1)
    }

    func test_cycle_region_moves_active_index() {
        let m = AnnotationModel()
        m.appendRegionBbox(box(0, 0, 100, 100))
        m.appendRegionBbox(box(200, 0, 100, 100))   // active = #2
        XCTAssertEqual(m.activeRegionIndex, 2)
        m.cycleRegion(-1)
        XCTAssertEqual(m.activeRegionIndex, 1)
        m.cycleRegion(-1)                            // wrap
        XCTAssertEqual(m.activeRegionIndex, 2)
    }

    func test_select_sets_active_in_correct_entity() {
        let m = AnnotationModel()
        let r1 = box(0, 0, 100, 100)
        let r2 = box(200, 0, 100, 100)
        m.appendRegionBbox(r1)
        m.appendRegionBbox(r2)
        m.select(id: r1.id)
        XCTAssertEqual(m.activeRegionBbox?.id, r1.id)
    }

    func test_remove_active_region_reassigns_active() {
        let m = AnnotationModel()
        let r1 = box(0, 0, 100, 100)
        let r2 = box(200, 0, 100, 100)
        m.appendRegionBbox(r1)
        m.appendRegionBbox(r2)   // active = r2
        m.removeBbox(id: r2.id)
        XCTAssertEqual(m.activeRegionBbox?.id, r1.id)
    }

    func test_onChange_fires_on_mutation() {
        let m = AnnotationModel()
        var calls = 0
        m.onChange = { calls += 1 }
        m.appendRegionBbox(box(0, 0, 100, 100))
        m.markNullTumor()
        XCTAssertEqual(calls, 2)
    }
}

// MARK: - Phase 10: dismissed detections (FP-сигнал)

extension AnnotationModelTests {
    private func prefillBox(detectionId: UUID, monitor: Int = 0) -> Bbox {
        Bbox(
            rect: CGRect(x: 0, y: 0, width: 100, height: 100),
            monitorIndex: monitor,
            originalDetectionId: detectionId
        )
    }

    func test_remove_prefill_region_records_dismissed_detection() {
        let detId = UUID()
        let m = AnnotationModel(
            entryMode: .edit,
            regionState: .bboxes([prefillBox(detectionId: detId)]),
            tumorState: .null
        )
        m.removeBbox(id: m.regionState.bboxes.first!.id)
        XCTAssertEqual(m.dismissedRegionDetections.count, 1)
        XCTAssertEqual(m.dismissedRegionDetections[0].detectionId, detId)
    }

    func test_mark_null_region_records_all_dismissed_region_and_tumor_detections() {
        let r1 = UUID()
        let r2 = UUID()
        let t1 = UUID()
        let m = AnnotationModel(
            entryMode: .edit,
            regionState: .bboxes([
                prefillBox(detectionId: r1),
                prefillBox(detectionId: r2),
            ]),
            tumorState: .bboxes([prefillBox(detectionId: t1)])
        )
        m.markNullRegion()
        XCTAssertEqual(
            Set(m.dismissedRegionDetections.map(\.detectionId)),
            [r1, r2]
        )
        // Каскад: tumors тоже dismissed.
        XCTAssertEqual(
            Set(m.dismissedTumorDetections.map(\.detectionId)),
            [t1]
        )
    }

    func test_mark_null_tumor_records_only_tumor_detections() {
        let r1 = UUID()
        let t1 = UUID()
        let m = AnnotationModel(
            entryMode: .edit,
            regionState: .bboxes([prefillBox(detectionId: r1)]),
            tumorState: .bboxes([prefillBox(detectionId: t1)])
        )
        m.markNullTumor()
        XCTAssertTrue(m.dismissedRegionDetections.isEmpty)
        XCTAssertEqual(m.dismissedTumorDetections.count, 1)
        XCTAssertEqual(m.dismissedTumorDetections[0].detectionId, t1)
    }

    func test_cold_start_remove_bbox_does_not_record_dismissed() {
        // Bbox без originalDetectionId (юзер нарисовал с нуля) — не попадает
        // в dismissed-список, так как нечего корректировать на сервере.
        let m = AnnotationModel()
        m.appendRegionBbox(box(0, 0, 100, 100))
        let id = m.regionState.bboxes[0].id
        m.removeBbox(id: id)
        XCTAssertTrue(m.dismissedRegionDetections.isEmpty)
    }

    func test_mixed_touch_preserves_prefill_id_after_update() {
        // Ключевой кейс: prefill bbox двигается → originalDetectionId
        // сохраняется в обновлённой версии bbox'а. При Send AnnotationSubmitter
        // отправит его как corrected + detection_id.
        let detId = UUID()
        let m = AnnotationModel(
            entryMode: .edit,
            regionState: .bboxes([prefillBox(detectionId: detId)]),
            tumorState: .null
        )
        let id = m.regionState.bboxes[0].id
        m.updateBbox(id: id, rect: CGRect(x: 50, y: 50, width: 100, height: 100))
        XCTAssertEqual(m.regionState.bboxes[0].originalDetectionId, detId)
        XCTAssertEqual(m.regionState.bboxes[0].rect.origin.x, 50)
        XCTAssertTrue(m.dismissedRegionDetections.isEmpty)
    }
}
