import XCTest
@testable import BrainScan

final class WidgetStatusTests: XCTestCase {
    func test_connected_dot_is_green_and_lists_two_versions() {
        let status = WidgetStatus.connected(localizerVersion: "v1.4", tumorVersion: "v1.4")
        XCTAssertEqual(status.dotColor, .systemGreen)
        XCTAssertEqual(status.primaryText, "Server Connected")
        XCTAssertEqual(status.secondaryLines, ["Localizer: v1.4", "Tumor Detector: v1.4"])
        XCTAssertFalse(status.showsWarningGlyph)
        XCTAssertTrue(status.isDetectEnabled)
    }

    func test_syncing_dot_is_yellow_and_shows_progress() {
        let status = WidgetStatus.syncing(uploaded: 7, total: 12)
        XCTAssertEqual(status.dotColor, .systemYellow)
        XCTAssertEqual(status.primaryText, "Syncing")
        XCTAssertEqual(status.secondaryLines, ["7/12 screens"])
        XCTAssertFalse(status.isDetectEnabled)
    }

    func test_no_models_dot_is_orange_and_keeps_detect_disabled() {
        let status = WidgetStatus.noModels(localAnnotations: 3)
        XCTAssertEqual(status.dotColor, .systemOrange)
        XCTAssertEqual(status.primaryText, "Server connected")
        XCTAssertEqual(status.secondaryLines.count, 2)
        XCTAssertTrue(status.secondaryLines[1].contains("3"))
        XCTAssertFalse(status.isDetectEnabled)
    }

    func test_no_server_dot_is_red_and_shows_warning() {
        let status = WidgetStatus.noServer(localAnnotations: 0)
        XCTAssertEqual(status.dotColor, .systemRed)
        XCTAssertEqual(status.primaryText, "No connection with server")
        XCTAssertTrue(status.showsWarningGlyph)
        XCTAssertFalse(status.isDetectEnabled)
    }

    func test_service_unavailable_has_no_secondary_lines() {
        let status = WidgetStatus.serviceUnavailable
        XCTAssertEqual(status.dotColor, .systemRed)
        XCTAssertEqual(status.primaryText, "Service is not available")
        XCTAssertTrue(status.secondaryLines.isEmpty)
        XCTAssertTrue(status.showsWarningGlyph)
        XCTAssertFalse(status.isDetectEnabled)
    }
}
