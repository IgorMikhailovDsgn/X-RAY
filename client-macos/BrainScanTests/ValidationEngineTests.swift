import XCTest
@testable import BrainScan

final class ValidationEngineTests: XCTestCase {
    private func box(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat,
                     monitor: Int = 0) -> Bbox {
        Bbox(rect: CGRect(x: x, y: y, width: w, height: h), monitorIndex: monitor)
    }

    func test_valid_region_with_contained_tumor_has_no_errors() {
        let r = box(0, 0, 100, 100)
        let t = box(10, 10, 30, 30)
        let errors = ValidationEngine.validate(region: .bboxes([r]), tumor: .bboxes([t]))
        XCTAssertTrue(errors.isEmpty)
    }

    func test_too_small_bbox_flagged() {
        let r = box(0, 0, 100, 100)
        let t = box(10, 10, 5, 30)   // ширина < 10
        let errors = ValidationEngine.validate(region: .bboxes([r]), tumor: .bboxes([t]))
        XCTAssertEqual(errors[t.id], .tooSmall)
    }

    func test_tumor_outside_region_flagged() {
        let r = box(0, 0, 100, 100)
        let t = box(120, 120, 20, 20)   // вне региона
        let errors = ValidationEngine.validate(region: .bboxes([r]), tumor: .bboxes([t]))
        XCTAssertEqual(errors[t.id], .tumorOutsideRegion)
    }

    func test_tumor_partially_outside_region_flagged() {
        let r = box(0, 0, 100, 100)
        let t = box(90, 90, 30, 30)   // вылезает за правый-нижний край
        let errors = ValidationEngine.validate(region: .bboxes([r]), tumor: .bboxes([t]))
        XCTAssertEqual(errors[t.id], .tumorOutsideRegion)
    }

    func test_overlapping_tumors_both_flagged() {
        let r = box(0, 0, 200, 200)
        let t1 = box(10, 10, 50, 50)
        let t2 = box(40, 40, 50, 50)   // пересекается с t1
        let errors = ValidationEngine.validate(region: .bboxes([r]), tumor: .bboxes([t1, t2]))
        XCTAssertEqual(errors[t1.id], .tumorOverlap)
        XCTAssertEqual(errors[t2.id], .tumorOverlap)
    }

    func test_tumor_on_different_monitor_not_contained() {
        let r = box(0, 0, 100, 100, monitor: 0)
        let t = box(10, 10, 20, 20, monitor: 1)   // тот же rect, другой монитор
        let errors = ValidationEngine.validate(region: .bboxes([r]), tumor: .bboxes([t]))
        XCTAssertEqual(errors[t.id], .tumorOutsideRegion)
    }

    func test_null_states_have_no_errors() {
        let errors = ValidationEngine.validate(region: .null, tumor: .null)
        XCTAssertTrue(errors.isEmpty)
    }
}
